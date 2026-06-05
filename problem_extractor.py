#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
题目信息提取器
功能：
1. 读取指定网页的源代码
2. 从HTML的<main>标签中提取题目信息
3. 将获取到的题目信息过滤、提取、拼接为纯文本形式，保存到.txt文件
"""

import re
import urllib.request
import urllib.error
from html.parser import HTMLParser


class ProblemExtractor(HTMLParser):
    """题目信息提取器 - 继承HTMLParser用于文本提取"""

    def __init__(self):
        super().__init__()
        self.text_parts = []
        self.skip_tags = {'script', 'style', 'button', 'a', 'footer', 'nav'}
        self.skip_count = 0

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

    def fetch_webpage(self, url):
        """
        读取指定网页的源代码

        Args:
            url: 网页URL

        Returns:
            str: 网页HTML源代码
        """
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=30) as response:
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

    def extract(self, url):
        """
        提取题目信息的主函数

        Args:
            url: 网页URL

        Returns:
            dict: 包含提取结果的字典
        """
        result = {
            'url': url,
            'problem_text': '',
            'success': False
        }

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
            result['problem_text'] = self.html_to_text(main_content)
            result['success'] = True
        else:
            print("未找到<main>标签，无法提取题目信息")

        return result

    def save_to_file(self, text, filename='problem_info.txt'):
        """
        将文本保存到文件

        Args:
            text: 要保存的文本
            filename: 文件名

        Returns:
            bool: 是否保存成功
        """
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(text)
            print(f"文本已保存到: {filename}")
            return True
        except Exception as e:
            print(f"保存文件时出错: {e}")
            return False


def main():
    """主函数"""
    extractor = ProblemExtractor()

    url = input("请输入网页URL: ").strip()
    if not url:
        print("URL不能为空")
        return

    result = extractor.extract(url)

    if result['success']:
        print("\n" + "=" * 50)
        print("提取的题目信息:")
        print("=" * 50)
        preview = result['problem_text'][:500]
        print(preview + "..." if len(result['problem_text']) > 500 else preview)

        default_filename = 'problem_info.txt'
        filename = input(f"\n请输入保存文件名（默认: {default_filename}）: ").strip()
        if not filename:
            filename = default_filename

        extractor.save_to_file(result['problem_text'], filename)
    else:
        print("未能提取到题目信息")


if __name__ == '__main__':
    main()
