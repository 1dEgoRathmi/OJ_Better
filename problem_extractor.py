#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
题目信息提取器
功能：
1. 支持认证登录（含验证码OCR识别），获取必要的cookie
2. 读取指定网页的源代码
3. 从HTML的<main>标签中提取题目信息
4. 将获取到的题目信息过滤、提取、拼接为纯文本形式，保存到.txt文件
"""

import re
import urllib.request
import urllib.error
import urllib.parse
import http.cookiejar
import json
from html.parser import HTMLParser
import ddddocr


class ProblemExtractor(HTMLParser):
    """题目信息提取器 - 继承HTMLParser用于文本提取"""

    def __init__(self):
        super().__init__()
        self.text_parts = []
        self.skip_tags = {"script", "style", "button", "a", "footer", "nav"}
        self.skip_count = 0
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = None
        self.base_url = "https://oj.ytu.edu.cn"
        self.ocr = ddddocr.DdddOcr(show_ad=False)  # 初始化ddddocr
        self._build_opener()

    def _build_opener(self):
        """构建带cookie处理的opener"""
        cookie_processor = urllib.request.HTTPCookieProcessor(self.cookie_jar)
        self.opener = urllib.request.build_opener(cookie_processor)
        self.opener.addheaders = [
            (
                "User-Agent",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            ),
            (
                "Accept",
                "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            ),
            ("Accept-Language", "zh-CN,zh;q=0.9,en;q=0.8"),
            ("Connection", "keep-alive"),
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
        captcha_url = f"{self.base_url}/vcode.php"
        print(f"正在获取验证码: {captcha_url}")

        try:
            # 下载验证码图片
            request = urllib.request.Request(captcha_url)
            response = self.opener.open(request, timeout=30)
            image_data = response.read()

            # 使用ddddocr识别验证码
            captcha_text = self.ocr.classification(image_data)

            # 清理识别结果（去除空格和换行）
            captcha_text = captcha_text.strip().replace(" ", "").replace("\n", "")

            print(f"验证码识别结果: {captcha_text}")
            return captcha_text

        except Exception as e:
            print(f"获取或识别验证码时出错: {e}")
            # 如果OCR失败，让用户手动输入
            return input("请手动输入验证码: ").strip()

    def authenticate(self, login_url):
        """
        进行认证登录，获取cookie

        Args:
            login_url: 登录页面URL

        Returns:
            bool: 认证是否成功
        """
        print("\n" + "=" * 50)
        print("需要进行认证登录")
        print("=" * 50)

        # 获取用户输入
        username = input("请输入账号: ").strip()
        password = input("请输入密码: ").strip()

        if not username or not password:
            print("账号和密码不能为空")
            return False

        try:
            # 首先访问登录页面获取必要的表单信息
            print(f"\n正在访问登录页面: {login_url}")
            response = self.opener.open(login_url, timeout=30)
            login_page_html = response.read().decode("utf-8", errors="ignore")
            print("已获取登录页面")

            # 获取验证码
            vcode = self._get_captcha()
            if not vcode:
                print("验证码不能为空")
                return False

            # 构建登录表单数据（根据登录页源代码）
            login_data = {
                "user_id": username,
                "password": password,
                "vcode": vcode,
                "rememberMe": "on",
                "nojs": "",
                "submit": "",
            }

            # 登录提交URL（根据登录页源代码中的form action）
            form_action = f"{self.base_url}/login.php"

            print(f"正在提交登录请求到: {form_action}")

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

            # 根据登录页源代码，返回的是JSON格式
            try:
                result = json.loads(response_data)
                if result.get("success") == 1:
                    print("登录成功！")
                    self._print_cookies()
                    return True
                elif result.get("success") == 0:
                    print(f"登录失败: {result.get('error', '未知错误')}")
                    return False
                elif result.get("success") == 2:
                    print(f"登录警告: {result.get('warning', '有警告但继续')}")
                    print("登录成功！")
                    self._print_cookies()
                    return True
                else:
                    # 如果不是JSON格式，按原来的方式检查
                    return self._check_login_success(response_data)
            except json.JSONDecodeError:
                # 返回的不是JSON，按HTML处理
                if self._check_login_success(response_data):
                    print("登录成功！")
                    self._print_cookies()
                    return True
                else:
                    print("登录失败")
                    return False

        except urllib.error.URLError as e:
            print(f"网络错误: {e}")
            return False
        except Exception as e:
            print(f"认证时出错: {e}")
            return False

    def _check_login_success(self, html):
        """
        检查登录是否成功（备用方法）

        Args:
            html: 登录后的页面HTML

        Returns:
            bool: 是否登录成功
        """
        # 检查常见的登录失败标志
        error_patterns = [
            r"密码错误",
            r"账号不存在",
            r"login failed",
            r"invalid password",
            r"用户名或密码错误",
            r"验证码错误",
            r"验证码",
        ]

        for pattern in error_patterns:
            if re.search(pattern, html, re.IGNORECASE):
                return False

        # 检查登录成功标志
        success_patterns = [
            r"logout\.php",
            r"注销",
            r"退出登录",
            r"欢迎",
            r"userinfo\.php",
        ]

        for pattern in success_patterns:
            if re.search(pattern, html, re.IGNORECASE):
                return True

        # 默认认为成功（如果页面能正常访问）
        return True

    def _print_cookies(self):
        """打印获取到的cookie信息"""
        print("\n已获取的Cookies:")
        print("-" * 50)

        target_cookies = ["remember", "lastlang", "PHPSESSID", "wengine_new_ticket"]
        found_cookies = {}

        for cookie in self.cookie_jar:
            if cookie.name in target_cookies:
                found_cookies[cookie.name] = cookie.value
                print(
                    f"{cookie.name}: {cookie.value[:30]}..."
                    if len(cookie.value) > 30
                    else f"{cookie.name}: {cookie.value}"
                )

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

            content_type = response.headers.get("Content-Type", "")
            charset_match = re.search(r"charset=([\w-]+)", content_type)
            encoding = charset_match.group(1) if charset_match else "utf-8"

            try:
                return response.read().decode(encoding)
            except UnicodeDecodeError:
                return response.read().decode("utf-8", errors="ignore")
        except urllib.error.URLError as e:
            print(f"网络错误: {e}")
            return None
        except Exception as e:
            print(f"获取网页时出错: {e}")
            return None

    def extract_problem_from_main(self, html):
        """
        从HTML的<main>标签中提取题目信息

        Args:
            html: 网页HTML源代码

        Returns:
            str: 包含题目信息的HTML代码段
        """
        main_match = re.search(r"<main[^>]*>([\s\S]*?)</main>", html, re.IGNORECASE)
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
        text = " ".join(self.text_parts)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def extract(self, url):
        """
        提取题目信息的主函数

        Args:
            url: 网页URL

        Returns:
            dict: 包含提取结果的字典
        """
        result = {"url": url, "problem_text": "", "success": False}

        print(f"正在读取网页: {url}")
        html = self.fetch_webpage(url)
        if not html:
            print("无法获取网页内容")
            return result

        print(f"HTML内容长度: {len(html)} 字符")
        print("正在提取题目信息...")

        main_content = self.extract_problem_from_main(html)
        if main_content:
            print("从<main>标签提取到题目信息")
            result["problem_text"] = self.html_to_text(main_content)
            result["success"] = True
        else:
            print("未找到<main>标签，无法提取题目信息")

        return result

    def save_to_file(self, text, filename="problem_info.txt"):
        """
        将文本保存到文件

        Args:
            text: 要保存的文本
            filename: 文件名

        Returns:
            bool: 是否保存成功
        """
        try:
            with open(filename, "w", encoding="utf-8") as f:
                f.write(text)
            print(f"文本已保存到: {filename}")
            return True
        except Exception as e:
            print(f"保存文件时出错: {e}")
            return False


def main():
    """主函数"""
    extractor = ProblemExtractor()

    # 目标题目URL
    target_url = "https://oj.ytu.edu.cn/problem.php?cid=5614&pid=7"
    login_url = "https://oj.ytu.edu.cn/loginpage.php"

    print("=" * 50)
    print("YTUOJ 题目信息提取器")
    print("=" * 50)

    # 访问逻辑：登录页 -> 题目页
    # 先进行登录认证
    print("\n访问流程：登录页 -> 题目页")
    if not extractor.authenticate(login_url):
        print("认证失败，程序退出")
        return

    # 登录成功后，访问目标页面获取题目
    print(f"\n正在获取题目信息: {target_url}")
    result = extractor.extract(target_url)

    if result["success"]:
        print("\n" + "=" * 50)
        print("提取的题目信息:")
        print("=" * 50)
        preview = result["problem_text"][:500]
        print(preview + "..." if len(result["problem_text"]) > 500 else preview)

        default_filename = "problem_info.txt"
        filename = input(f"\n请输入保存文件名（默认: {default_filename}）: ").strip()
        if not filename:
            filename = default_filename

        extractor.save_to_file(result["problem_text"], filename)
    else:
        print("未能提取到题目信息")


if __name__ == "__main__":
    main()
