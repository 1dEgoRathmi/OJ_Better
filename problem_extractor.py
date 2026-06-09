#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
题目信息提取器
功能：
1. 支持认证登录（含验证码OCR识别），获取必要的cookie
2. 读取指定网页的源代码
3. 从HTML的<main>标签中提取题目信息
4. 将获取到的题目信息过滤、提取、拼接为纯文本形式，保存到.txt文件
5. 提取我的竞赛&作业列表，访问进行中作业，抓取未完成的题目信息
6. 调用DeepSeek API解题并自动提交到OJ
"""

import re
import urllib.request
import urllib.error
import urllib.parse
import http.cookiejar
import json
from html.parser import HTMLParser
import ddddocr
from openai import OpenAI


def waf_encode(code):
    """OJ提交所需：将源代码编码为十六进制管道格式"""
    return '|'.join(hex(ord(c))[2:] for c in code)


class ProblemExtractor(HTMLParser):
    """题目信息提取器 - 继承HTMLParser用于文本提取"""

    def __init__(self):
        super().__init__()
        self.text_parts = []
        self.skip_tags = {'script', 'style', 'button', 'a', 'footer', 'nav'}
        self.skip_count = 0
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = None
        self.base_url = 'https://oj.ytu.edu.cn'
        self.ocr = ddddocr.DdddOcr(show_ad=False)  # 初始化ddddocr
        self.deepseek_api_key = ''  # DeepSeek API密钥
        self._build_opener()

    def _build_opener(self):
        """构建带cookie处理的opener"""
        cookie_processor = urllib.request.HTTPCookieProcessor(self.cookie_jar)
        self.opener = urllib.request.build_opener(cookie_processor)
        self.opener.addheaders = [
            ('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'),
            ('Accept', 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'),
            ('Accept-Language', 'zh-CN,zh;q=0.9,en;q=0.8'),
            ('Connection', 'keep-alive'),
        ]

    def handle_starttag(self, tag, attrs):
        if tag in self.skip_tags:
            self.skip_count += 1

    def handle_endtag(self, tag):
        if tag in self.skip_tags:
            self.skip_count -= 1

    def handle_data(self, data):
        if self.skip_count == 0:
            cleaned = data.strip()
            if cleaned:
                self.text_parts.append(cleaned)

    def reset_parser(self):
        """重置解析器状态"""
        super().reset()
        self.text_parts = []
        self.skip_count = 0

    def _get_captcha(self):
        """
        获取验证码图片并进行OCR识别

        Returns:
            str: 识别出的验证码文本
        """
        captcha_url = f'{self.base_url}/vcode.php'
        print(f"正在获取验证码: {captcha_url}")

        try:
            # 下载验证码图片
            request = urllib.request.Request(captcha_url)
            response = self.opener.open(request, timeout=30)
            image_data = response.read()

            # 使用ddddocr识别验证码
            captcha_text = self.ocr.classification(image_data)

            # 清理识别结果（去除空格和换行）
            captcha_text = captcha_text.strip().replace(' ', '').replace('\n', '')

            print(f"验证码识别结果: {captcha_text}")
            return captcha_text

        except Exception as e:
            print(f"获取或识别验证码时出错: {e}")
            # 如果OCR失败，让用户手动输入
            return input("请手动输入验证码: ").strip()

    def _try_login(self, login_url, username, password, vcode):
        """
        尝试登录一次

        Args:
            login_url: 登录页面URL
            username: 用户名
            password: 密码
            vcode: 验证码

        Returns:
            tuple: (是否成功, 是否需要重试, 响应数据)
        """
        # 构建登录表单数据
        login_data = {
            "user_id": username,
            "password": password,
            "vcode": vcode,
            "rememberMe": "true",
            "nojs": "",
            "submit": "",
        }

        form_action = f"{self.base_url}/login.php"

        # 编码表单数据
        encoded_data = urllib.parse.urlencode(login_data).encode("utf-8")

        # 创建登录请求
        login_request = urllib.request.Request(
            form_action,
            data=encoded_data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": login_url,
            },
            method="POST",
        )

        # 发送登录请求
        response = self.opener.open(login_request, timeout=30)
        response_data = response.read().decode("utf-8", errors="ignore")

        # 检查登录成功标志
        if 'userinfo.php?user=' in response_data or 'logout.php' in response_data:
            return True, False, response_data

        # 检查验证码错误
        if '验证码' in response_data and ('错误' in response_data or '不正确' in response_data):
            return False, True, response_data  # 需要重试

        # 其他错误（密码错误、账号不存在等）
        return False, False, response_data

    def authenticate(self, login_url):
        """
        进行认证登录，获取cookie（支持验证码错误重试）

        Args:
            login_url: 登录页面URL

        Returns:
            bool: 认证是否成功
        """
        print("\n" + "=" * 50)
        print("【页面1/4】登录页面 - 需要进行认证登录")
        print("=" * 50)

        # 获取用户输入
        username = input("请输入账号: ").strip()
        password = input("请输入密码: ").strip()

        if not username or not password:
            print("账号和密码不能为空")
            return False

        try:
            # 首先访问登录页面
            print(f"\n正在访问登录页面: {login_url}")
            response = self.opener.open(login_url, timeout=30)
            login_page_html = response.read().decode("utf-8", errors="ignore")
            print("已获取登录页面")

            # 验证码错误重试机制（最多10次）
            max_retries = 10
            for attempt in range(1, max_retries + 1):
                print(f"\n--- 第 {attempt} 次登录尝试 ---")

                # 获取验证码
                vcode = self._get_captcha()
                if not vcode:
                    print("验证码不能为空")
                    continue

                # 尝试登录
                try:
                    success, need_retry, response_data = self._try_login(
                        login_url, username, password, vcode
                    )

                    if success:
                        print("登录成功！")
                        self._print_cookies()
                        return True

                    if need_retry and attempt < max_retries:
                        print("验证码错误，准备重试...")
                        continue
                    else:
                        # 其他错误或已达到最大重试次数
                        print("检查账号密码信息、平台考试状态或网络问题")
                        return False

                except urllib.error.URLError as e:
                    print("检查账号密码信息、平台考试状态或网络问题")
                    return False
                except Exception as e:
                    print("检查账号密码信息、平台考试状态或网络问题")
                    return False

            # 达到最大重试次数
            print("验证码错误次数过多，请稍后重试")
            return False

        except urllib.error.URLError as e:
            print("检查账号密码信息、平台考试状态或网络问题")
            return False
        except Exception as e:
            print("检查账号密码信息、平台考试状态或网络问题")
            return False

    def _print_cookies(self):
        """打印获取到的cookie信息"""
        print("\n已获取的Cookies:")
        print("-" * 50)

        target_cookies = ['remember', 'lastlang', 'PHPSESSID', 'wengine_new_ticket']
        found_cookies = {}

        for cookie in self.cookie_jar:
            if cookie.name in target_cookies:
                found_cookies[cookie.name] = cookie.value
                print(f"{cookie.name}: {cookie.value[:30]}..." if len(cookie.value) > 30 else f"{cookie.name}: {cookie.value}")

        # 显示未获取到的cookie
        for name in target_cookies:
            if name not in found_cookies:
                print(f"{name}: 未获取到")

        print("-" * 50)

    def fetch_webpage(self, url):
        """
        读取指定网页的源代码

        Args:
            url: 网页URL

        Returns:
            str: 网页HTML源代码
        """
        try:
            request = urllib.request.Request(url)
            response = self.opener.open(request, timeout=30)

            content_type = response.headers.get('Content-Type', '')
            charset_match = re.search(r'charset=([\w-]+)', content_type)
            encoding = charset_match.group(1) if charset_match else 'utf-8'

            try:
                return response.read().decode(encoding)
            except UnicodeDecodeError:
                return response.read().decode('utf-8', errors='ignore')
        except urllib.error.URLError as e:
            print(f"网络错误: {e}")
            return None
        except Exception as e:
            print(f"获取网页时出错: {e}")
            return None

    def extract_active_cids(self, html):
        """
        从HTML中提取进行中的作业CID列表

        Args:
            html: 网页HTML源代码

        Returns:
            list: 进行中作业的CID列表
        """
        active_cids = []

        # 匹配表格中的每一行
        row_pattern = r'<tr>\s*<td>(\d+)</td>\s*<td><a[^>]*href="contest\.php\?cid=(\d+)"[^>]*>([^<]+)</a></td>\s*<td>(.*?)</td>'
        matches = re.findall(row_pattern, html, re.DOTALL)

        for match in matches:
            cid, cid2, name, status_html = match
            name = name.strip()

            # 只记录进行中的作业
            if '运行中' in status_html or 'text-danger' in status_html:
                active_cids.append({
                    'cid': cid,
                    'name': name
                })

        return active_cids

    def extract_problem_from_main(self, html):
        """
        从HTML的<main>标签中提取题目信息

        Args:
            html: 网页HTML源代码

        Returns:
            str: 包含题目信息的HTML代码段
        """
        main_match = re.search(r'<main[^>]*>([\s\S]*?)</main>', html, re.IGNORECASE)
        return main_match.group(1) if main_match else None

    def html_to_text(self, html):
        """
        将HTML转换为纯文本

        Args:
            html: HTML代码

        Returns:
            str: 纯文本
        """
        self.reset_parser()
        self.feed(html)
        text = ' '.join(self.text_parts)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def extract_problem_details(self, url):
        """
        提取题目详细信息

        Args:
            url: 题目页面URL

        Returns:
            str: 题目文本内容
        """
        print(f"\n  正在读取题目页面: {url}")
        html = self.fetch_webpage(url)
        if not html:
            print("  无法获取题目内容")
            return None

        main_content = self.extract_problem_from_main(html)
        if main_content:
            return self.html_to_text(main_content)
        else:
            print("  未找到题目内容")
            return None

    def solve_with_deepseek(self, problem_text):
        """
        调用 DeepSeek API（v4-pro模型）解题

        Args:
            problem_text: 题目文本

        Returns:
            str: 解题代码，失败返回 None
        """
        print("  正在调用 DeepSeek v4-pro API 解题...")

        prompt = (
            "你是一个算法竞赛专家。请根据以下OJ题目描述，编写可直接提交的Python代码解答。\n"
            "要求：\n"
            "1. 只输出纯代码，不要包含任何解释文字、markdown标记（如```python```）、注释\n"
            "2. 使用 sys.stdin.read 或 input() 读取输入，使用 print() 输出结果\n"
            "3. 代码要简洁、正确、高性能\n\n"
            f"题目描述：\n{problem_text}"
        )

        try:
            client = OpenAI(
                api_key=self.deepseek_api_key,
                base_url="https://api.deepseek.com"
            )

            response = client.chat.completions.create(
                model="deepseek-v4-pro",
                messages=[
                    {"role": "system", "content": "你是一个算法竞赛专家，只输出解题代码。"},
                    {"role": "user", "content": prompt}
                ],
                stream=False,
                reasoning_effort="high",
                extra_body={"thinking": {"type": "enabled"}}
            )

            code = response.choices[0].message.content

            # 清理可能的 markdown 标记
            code = re.sub(r'^```(?:python)?\s*\n?', '', code)
            code = re.sub(r'\n?```\s*$', '', code)
            code = code.strip()

            print(f"  解题成功，代码长度: {len(code)} 字符")
            return code
        except Exception as e:
            print(f"  DeepSeek API 调用失败: {e}")
            return None

    def submit_solution(self, cid, pid, code):
        """
        提交代码到 OJ（页面5：提交页面）

        Args:
            cid: 竞赛ID
            pid: 题目ID
            code: Python源代码

        Returns:
            bool: 是否提交成功
        """
        submit_url = f'{self.base_url}/submit.php'

        print(f"  正在提交代码到 OJ: cid={cid}, pid={pid}")

        # waf_encode 编码源代码
        encoded_source = waf_encode(code)

        # 构建提交表单数据
        submit_data = {
            'cid': str(cid),
            'pid': str(pid),
            'language': '6',  # 6 = Python
            'source': encoded_source
        }

        # 编码表单数据
        encoded_data = urllib.parse.urlencode(submit_data).encode('utf-8')

        # 创建提交请求（携带登录状态的cookie）
        submit_request = urllib.request.Request(
            submit_url,
            data=encoded_data,
            headers={
                'Content-Type': 'application/x-www-form-urlencoded',
                'Referer': f'{self.base_url}/submitpage.php?cid={cid}&pid={pid}'
            },
            method='POST'
        )

        try:
            response = self.opener.open(submit_request, timeout=30)
            response_data = response.read().decode('utf-8', errors='ignore')

            # 检查提交结果
            if 'success' in response_data.lower() or response.status == 200:
                print("  提交成功！")
                return True
            else:
                print(f"  提交可能失败，服务器返回长度: {len(response_data)}")
                return True  # 通常200就表示提交成功
        except urllib.error.URLError as e:
            print(f"  提交失败: {e}")
            return False
        except Exception as e:
            print(f"  提交时出错: {e}")
            return False

    def save_problems_to_file(self, all_problems, filename='all_problems.txt'):
        """
        将所有题目信息保存到文件

        Args:
            all_problems: 所有题目的列表
            filename: 文件名

        Returns:
            bool: 是否保存成功
        """
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write("=" * 60 + "\n")
                f.write("YTUOJ 题目信息汇总\n")
                f.write("=" * 60 + "\n\n")

                for i, problem in enumerate(all_problems, 1):
                    f.write(f"题目 {i}\n")
                    f.write("-" * 60 + "\n")
                    f.write(f"来源: {problem.get('contest_name', '未知')}\n")
                    f.write(f"CID: {problem.get('cid', '未知')}, PID: {problem.get('pid', '未知')}\n")
                    f.write(f"题目名称: {problem.get('name', '未知')}\n")
                    f.write("\n")
                    f.write(problem.get('content', '无内容'))
                    f.write("\n\n")
                    f.write("=" * 60 + "\n\n")

            print(f"\n所有题目信息已保存到: {filename}")
            print(f"共保存 {len(all_problems)} 道题目")
            return True
        except Exception as e:
            print(f"保存文件时出错: {e}")
            return False


def main():
    """主函数"""
    extractor = ProblemExtractor()

    # URL配置
    my_contests_url = 'https://oj.ytu.edu.cn/contest.php?my'
    login_url = 'https://oj.ytu.edu.cn/loginpage.php'

    print("=" * 60)
    print("YTUOJ 题目信息提取器")
    print("=" * 60)

    # 输入 DeepSeek API Key
    api_key = input("请输入 DeepSeek API Key（回车跳过自动解题）: ").strip()
    if api_key:
        extractor.deepseek_api_key = api_key
        print("已设置 DeepSeek API Key，将自动解题并提交")
    else:
        print("未设置 API Key，将仅提取题目信息")

    # ========== 页面1: 登录页面 ==========
    print("\n程序流程: 登录页面 -> 主页面 -> 作业页面 -> 题目页面 -> 提交页面")
    if not extractor.authenticate(login_url):
        print("认证失败，程序退出")
        return

    # ========== 页面2: 主页面（我的竞赛&作业列表） ==========
    print("\n" + "=" * 60)
    print("【页面2/5】主页面 - 我的竞赛&作业列表")
    print("=" * 60)
    print(f"\n正在访问: {my_contests_url}")
    html = extractor.fetch_webpage(my_contests_url)

    if not html:
        print("无法获取主页面内容")
        return

    print(f"页面获取成功，长度: {len(html)} 字符")

    # 提取进行中作业的CID
    active_contests = extractor.extract_active_cids(html)

    if not active_contests:
        print("\n没有进行中的作业")
        return

    print(f"\n找到 {len(active_contests)} 个进行中的作业:")
    for i, contest in enumerate(active_contests, 1):
        print(f"  {i}. CID {contest['cid']}: {contest['name']}")

    # ========== 页面3: 作业页面 ==========
    print("\n" + "=" * 60)
    print("【页面3/5】作业页面 - 获取各作业的题目列表")
    print("=" * 60)

    all_incomplete_problems = []  # 存储所有未完成的题目

    for contest in active_contests:
        cid = contest['cid']
        contest_name = contest['name']
        contest_url = f"https://oj.ytu.edu.cn/contest.php?cid={cid}"

        print(f"\n正在访问作业页面: {contest_url}")
        contest_html = extractor.fetch_webpage(contest_url)

        if not contest_html:
            print(f"  无法获取CID {cid} 的作业页面")
            continue

        # 根据实际作业页面结构提取题目列表
        problem_rows = re.findall(
            r'<tr>\s*<td>(.*?)</td>\s*<td>([^<]+)</td>\s*<td><a[^>]*href="problem\.php\?cid=' + cid + r'&pid=(\d+)"[^>]*>([^<]+)</a></td>\s*<td[^>]*>([^<]*)</td>\s*<td>([^<]*)</td>\s*<td>([^<]*)</td>\s*</tr>',
            contest_html
        )

        print(f"  找到 {len(problem_rows)} 道题目")

        for status_col, problem_id, pid, title, source, accepted, submitted in problem_rows:
            # 判断完成状态：只有绿色勾表示已完成，其他状态（空、红色叉）都需要抓取
            is_completed = 'fa-check' in status_col and 'text-success' in status_col

            if is_completed:
                print(f"    - PID {pid}: {title.strip()} [已完成，跳过]")
            else:
                # 判断是错题还是未做
                if 'fa-times' in status_col or 'text-danger' in status_col:
                    status_text = "错题，将抓取"
                else:
                    status_text = "未完成，将抓取"
                print(f"    - PID {pid}: {title.strip()} [{status_text}]")
                all_incomplete_problems.append({
                    'cid': cid,
                    'contest_name': contest_name,
                    'pid': pid,
                    'problem_id': problem_id.strip(),
                    'name': title.strip(),
                    'source': source.strip(),
                    'accepted': accepted.strip(),
                    'submitted': submitted.strip(),
                    'url': f"https://oj.ytu.edu.cn/problem.php?cid={cid}&pid={pid}"
                })

    if not all_incomplete_problems:
        print("\n所有题目都已完成，没有需要抓取的题目")
        return

    print(f"\n共找到 {len(all_incomplete_problems)} 道未完成的题目")

    # ========== 页面4: 题目页面 ==========
    print("\n" + "=" * 60)
    print("【页面4/5】题目页面 - 抓取未完成的题目信息")
    print("=" * 60)

    for i, problem in enumerate(all_incomplete_problems, 1):
        print(f"\n[{i}/{len(all_incomplete_problems)}] 抓取题目: {problem['name']}")
        content = extractor.extract_problem_details(problem['url'])
        problem['content'] = content if content else "无法获取题目内容"

    # ========== 页面5: 提交页面 (DeepSeek解题 + 提交) ==========
    print("\n" + "=" * 60)
    print("【页面5/5】自动解题与提交")
    print("=" * 60)

    if extractor.deepseek_api_key:
        for i, problem in enumerate(all_incomplete_problems, 1):
            if not problem.get('content') or problem['content'] == "无法获取题目内容":
                print(f"\n[{i}/{len(all_incomplete_problems)}] 跳过（无题目内容）: {problem['name']}")
                continue

            print(f"\n[{i}/{len(all_incomplete_problems)}] 解题: {problem['name']}")

            # 调用 DeepSeek API 解题
            code = extractor.solve_with_deepseek(problem['content'])

            if code:
                # 提交代码到 OJ
                cid = problem['cid']
                pid = problem['pid']
                extractor.submit_solution(cid, pid, code)
            else:
                print(f"  跳过提交: {problem['name']}（解题失败）")
    else:
        print("\n未设置 DeepSeek API Key，跳过自动解题步骤")

    # 保存所有题目信息
    print("\n" + "=" * 60)
    print("保存题目信息")
    print("=" * 60)

    default_filename = 'all_problems.txt'
    filename = input(f"\n请输入保存文件名（默认: {default_filename}）: ").strip()
    if not filename:
        filename = default_filename

    extractor.save_problems_to_file(all_incomplete_problems, filename)

    print("\n" + "=" * 60)
    print("程序执行完毕")
    print("=" * 60)


if __name__ == '__main__':
    main()
