import json
import os
import pickle
import sqlite3
import time
import msedge.selenium_tools
import requests
import selenium.common.exceptions
import threading
from concurrent.futures import ThreadPoolExecutor
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as ec

import funcs

WAIT_TIME = 600  # 在登录页面等待10分钟
MAX_NUM = 131072

hds = {
    'referer': 'https://www.pixiv.net/',
    'User-Agent': 'Mozilla/5.0 (Linux; Android 5.0; SM-G900P Build/LRX21T) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.85 '
                  'Mobile Safari/537.36 Edg/90.0.818.46'
}


class StoppableThread(threading.Thread):

    def __init__(self, func=None, args=()):
        super().__init__()
        self.func = func
        self.args = args
        self.is_running = True

    def run(self):
        task = threading.Thread(
            target=self.func,
            args=self.args
        )
        task.setDaemon(True)
        task.start()
        while self.is_running and task.is_alive():
            task.join()
            time.sleep(0.5)

    def stop(self):
        self.is_running = False


class PixivLoginPage:

    def __init__(self, opt_proxy: str = ''):
        self.opt = msedge.selenium_tools.EdgeOptions()
        self.opt.use_chromium = True
        if opt_proxy:
            self.raw_proxy = opt_proxy
            self.proxy = '--proxy-server={pxy:s}'.format(pxy=opt_proxy)
            self.opt.add_argument(self.proxy)
        # 'eager' strategy can be found in the doc of selenium
        self.opt.page_load_options = 'eager'
        self.driver = None
        self.custom_cookie_list = None
        self.custom_cookie_dict = None

    def login(self, username: str, password: str):
        print('Start login as', username, '...', end='')
        if os.path.exists('cookie.pck'):
            with open('cookie.pck', 'rb') as f:
                try:
                    temp_cookie = pickle.load(f)[username]
                    expire_time = int(temp_cookie[0]['expiry'])
                    if int(time.time()) < expire_time:
                        self.custom_cookie_list = temp_cookie
                        self.custom_cookie_dict = funcs.sele2req(temp_cookie)
                        print('Login success.')
                        return None
                except KeyError:
                    pass
        login_url = 'https://accounts.pixiv.net/login'
        self.driver = msedge.selenium_tools.Edge('./msedgedriver.exe', options=self.opt)
        for i in range(1, 6):
            try:
                self.driver.get(login_url)
                WebDriverWait(self.driver, 30).until(ec.presence_of_element_located(
                    (By.XPATH, '//*[@class="signup-form__submit"]')
                ))
                un_elem = self.driver.find_element_by_xpath(
                    '//input[@autocomplete="username"]'
                )
                pw_elem = self.driver.find_element_by_xpath(
                    '//input[@autocomplete="current-password"]'
                )
                un_elem.clear()
                un_elem.send_keys(username)
                pw_elem.clear()
                pw_elem.send_keys(password)
                # Start to login
                un_elem.send_keys(Keys.RETURN)
                WebDriverWait(self.driver, WAIT_TIME).until(
                    ec.presence_of_element_located(
                        (By.XPATH, r'''//div[@id="root"]''')))
                break
            except selenium.common.exceptions.TimeoutException:
                print(f'Retrying login...{i:d}...')
        # useful when reusing our identity
        temp_cookie = {
            username: self.driver.get_cookies()
        }
        with open('cookie.pck', 'wb') as f:
            pickle.dump(temp_cookie, f)
        self.custom_cookie_list = temp_cookie
        self.custom_cookie_dict = funcs.sele2req(temp_cookie[username])
        self.driver.quit()
        print('Login success.')


class PixivMobileArtPage:

    def __init__(self, pixiv_id):
        self.url = f'https://www.pixiv.net/touch/ajax/illust/details?' \
                   f'illust_id={pixiv_id:s}&lang=zh'
        self.custom_proxy = None
        self.custom_cookies = None
        self.session = None
        self.like_num = -1
        self.is_R18 = False

    def set_proxy(self, new_proxy):
        if new_proxy:
            self.custom_proxy = {
                'http': new_proxy,
                'https': new_proxy
            }

    def set_cookies(self, new_cookies):
        self.custom_cookies = new_cookies

    def set_session(self, new_session):
        self.session = new_session

    def parse(self):
        for i in range(5):
            try:
                r = self.session.get(
                    self.url, headers=hds, timeout=10,
                    cookies=self.custom_cookies,
                    proxies=self.custom_proxy
                )
                r.raise_for_status()
                data_in_json = json.loads(r.content)
                try:
                    data_in_json = data_in_json['body']['illust_details']
                except KeyError:
                    continue
                tags = data_in_json['tags']
                if 'R-18' in tags or 'R-18G' in tags:
                    self.is_R18 = True
                self.like_num = int(data_in_json['bookmark_user_total'])
                break
            except:
                pass


class PixivMobilePage:

    def __init__(self):
        self.session = requests.Session()
        self.raw_proxy = None
        self.custom_proxy = None
        self.search_keyword = None
        self.custom_cookies = None
        self.current_page = 0
        self.total_page = 0
        self.total_num = 0
        self.lowest_like = 150
        self.url = 'https://www.pixiv.net/touch/ajax/search/illusts?' \
                   'include_meta=0&p={0:d}&type=all&word={1:s}' \
                   '&s_mode=s_tag_full&lang=zh'
        self.artworks = []
        self.search_thread = None
        self.go_ahead = True

    def set_proxy(self, new_proxy: str):
        if new_proxy:
            self.raw_proxy = new_proxy
            self.custom_proxy = {
                'http': new_proxy,
                'https': new_proxy
            }

    def set_search_keyword(self, new_keyword: str):
        self.search_keyword = new_keyword

    def set_cookies(self, dict_of_cookie: dict):
        self.custom_cookies = dict_of_cookie

    def parse_one_page(self, page=1):
        artworks = []
        for i in range(5):
            try:
                if self.custom_proxy:
                    r = self.session.get(
                        self.url.format(page, self.search_keyword),
                        headers=hds, timeout=10,
                        proxies=self.custom_proxy,
                        cookies=self.custom_cookies
                    )
                else:
                    r = self.session.get(
                        self.url.format(page, self.search_keyword),
                        headers=hds, timeout=10,
                        cookies=self.custom_cookies
                    )
                r.raise_for_status()
                data_in_json = json.loads(r.content)
                try:
                    data_in_json = data_in_json['body']
                except KeyError:
                    continue
                self.total_num = int(data_in_json['total'])
                if self.total_num % 15:
                    self.total_page = self.total_num // 15 + 1
                else:
                    self.total_page = self.total_num // 15
                self.current_page = page
                for each in data_in_json['illusts']:
                    temp = PixivMobileArtPage(each['id'])
                    temp.set_proxy(self.raw_proxy)
                    temp.set_cookies(self.custom_cookies)
                    temp.set_session(self.session)
                    temp.parse()
                    artworks.append({
                        'pixiv_id': each['id'],
                        'title': each['title'],
                        'thumb_url': each['url_s'].replace('\\', ''),
                        'like_num': temp.like_num,
                        'is_R18': temp.is_R18
                    })
                return artworks
            except:
                print('Retrying to parse page {}...trying {}...'.format(page, i+1))
        print('Failed to parse page', page, '.')
        return []

    def write_to_storage(self, search_keyword, artworks, lowest_like=150):
        # If not exists, program will create one.
        content = sqlite3.connect('storage.db')
        cur = content.cursor()
        search_keyword = search_keyword.replace('(', '_')
        search_keyword = search_keyword.replace(')', '')
        search_keyword = search_keyword.replace(' ', '_')
        search_keyword = search_keyword.replace('-', '_')
        try:
            cur.execute(f'CREATE TABLE {search_keyword:s} ('
                        f'    pixiv_id INT NOT NULL UNIQUE PRIMARY KEY,\n'
                        f'    title CHAR(1024) NOT NULL,\n'
                        f'    thumb_url CHAR(2048) NOT NULL,\n'
                        f'    like_num INT, \n'
                        f'    is_R18 INT\n'
                        f')')
            print(
                f'A new table {search_keyword:s} has been created...',
                end='', flush=True
            )
        except sqlite3.OperationalError:
            # The table has been created
            pass
        for each in artworks:
            try:
                if each['like_num'] < lowest_like:
                    continue
                t = (
                    each['pixiv_id'],
                    each['title'],
                    each['thumb_url'],
                    each['like_num'],
                    each['is_R18']
                )
                cur.execute(f'INSERT INTO {search_keyword:s} VALUES (?, ?, ?, ?, ?)', t)
            except sqlite3.OperationalError:
                print(f'''
                    INSERT INTO {search_keyword} VALUES (
                        \"{each['pixiv_id']}\",
                        \"{each['title']}\",
                        \"{each['thumb_url']}\",
                        \"{each['like_num']}\",
                        \"{each['is_R18']}\"
                )''')
            except sqlite3.IntegrityError:
                # This artwork has been added into the storage
                t = (each['like_num'], each['is_R18'], each['pixiv_id'])
                cur.execute(
                    f'UPDATE {search_keyword:s} SET like_num=?, is_R18=? WHERE pixiv_id=?',
                    t
                )
        cur.close()
        content.commit()
        content.close()

    def get_artworks_from_all_pages(self, _from=1, _to=MAX_NUM):
        # loop:
        #     parse_one_page -> write -> self.artworks.clear()
        def temp_func(a):
            if not self.go_ahead:
                return 0
            # self.current_page = a
            artworks = self.parse_one_page(a)
            print(f'Parsing page {a}/{self.total_page} Successfully.', flush=True)
            self.write_to_storage(self.search_keyword, artworks)
            if self.total_page == a:
                time.sleep(4)
                print(f'All pages of {self.search_keyword} has been parsed.')
                funcs.config_settings(self.search_keyword, a + 1 if a < self.total_page else 1)
            if not a%4:
                funcs.config_settings(self.search_keyword, a + 1 if a < self.total_page else 1)

        temp_func(_from)
        print(f'{self.search_keyword} has {self.total_num} artworks in total.')
        _from += 1

        if _to == MAX_NUM:
            _to = self.total_page

        def show_progress(a, b):
            with ThreadPoolExecutor(max_workers=12) as tp:
                tasks = []
                task_add = tasks.append
                while a <= b:
                    task_add(tp.submit(temp_func, a))
                    a += 1
        self.search_thread = StoppableThread(show_progress, (_from, _to))
        self.search_thread.start()
