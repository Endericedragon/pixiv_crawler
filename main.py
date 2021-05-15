import json
import os
import pickle
import sqlite3
import urllib.request

import classes
import funcs
import GUI


class Main:
    def __init__(self):
        self.t = None

    def start_to_run(self):
        try:
            with open('user_info.json', 'rb') as f:
                content = json.load(f)
                self.user_name = content['username']
                self.user_pass = content['password']
                self.user_proxy = content.get(
                    'proxy',
                    urllib.request.getproxies().get('http', None)
                )
        except (EOFError, KeyError, FileNotFoundError) as e:
            print(type(e), e)
            print(
                f'There\'s something wrong with user_info.json.\n'
                f'Please create a file called user_info.json in\n'
                f'the same directory of the program and type in\n'
                f'your pixiv account and password as follows:\n'
                f'{{\n'
                f'    "proxy": "your proxy here(with quotes). Delete this line if you\'re using global proxies.", \n'
                f'    "username": "your username here, with quotes", \n'
                f'    "password": "your password here, with quotes"\n'
                f'}}\n'
            )
            os.system('pause')
            return 0

        login_info = classes.PixivLoginPage(self.user_proxy)
        login_info.login(self.user_name, self.user_pass)

        self.network_module = classes.PixivMobilePage()
        self.network_module.set_proxy(self.user_proxy)
        self.network_module.set_cookies(login_info.custom_cookie_dict)

        self.app = GUI.App()


        try:
            with open('settings.pck', 'rb') as f:
                temp_dict = pickle.load(f)
                r18_option = temp_dict.get('r18', -1)
                if r18_option != -1:
                    self.app.show_R18 = r18_option
        except FileNotFoundError:
            with open('settings.pck', 'wb'):pass

        def t_start(_):
            self.app.load_pics_to_gui()
            if self.t:
                self.network_module.go_ahead = False
                self.t.stop()
            if self.network_module.search_thread:
                self.network_module.search_thread.stop()
            if self.t:
                self.t.join()
            if self.network_module.search_thread:
                self.network_module.search_thread.join()
            funcs.config_settings(
                self.network_module.search_keyword,
                self.network_module.current_page + 1
                if self.network_module.current_page + 1 < self.network_module.total_page else 1
            )
            self.app.search_keyword = self.app.search_input.get().strip()
            if not self.app.search_keyword:
                return None
            self.network_module.go_ahead = True
            self.network_module.set_search_keyword(self.app.search_keyword)

            with sqlite3.connect('storage.db') as f:
                self.app.get_works_from_db(self.app.search_keyword, 1, f, self.user_proxy)

            self.app.refresh_button.config(state='normal')
            temp_dict = {}
            try:
                with open('settings.pck', 'rb') as f:
                    temp_dict = pickle.load(f)
            except FileNotFoundError:
                pass
            except EOFError:
                pass
            self.t = classes.StoppableThread(
                self.network_module.get_artworks_from_all_pages,
                (temp_dict.get(self.app.search_keyword, 1),)
            )
            self.t.start()
            self.app.use_auto_refresh(True, False)

        self.app.search_input.bind(
            '<Return>', t_start
        )

        self.app.load_pics_to_gui()
        self.app.mainloop()

        funcs.config_settings(
            self.network_module.search_keyword,
            self.network_module.current_page+1
            if self.network_module.current_page+1 < self.network_module.total_page else 1
        )
        self.network_module.go_ahead = False
        if getattr(self.t, 'stop', False):
            self.t.stop()


if __name__ == '__main__':
    program = Main()
    program.start_to_run()
