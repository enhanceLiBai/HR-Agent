"""HR Agent 命令行交互入口。"""
import os
import sys

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(__file__))

# 加载 .env 环境变量
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    print("⚠ python-dotenv 未安装，将直接读取系统环境变量。pip install python-dotenv")


def main():
    from core.agent import chat
    from tools.employee import get_employee

    print("=" * 50)
    print("  HR Agent - 智能助手")
    print("  输入 'quit' 退出，输入 'switch <工号>' 切换身份")
    print("=" * 50)

    # 默认以王小明身份登录
    current_user = "emp_003"
    history = []

    # 显示当前身份
    print(f"\n当前身份: {get_employee(current_user)}")
    print("\n有什么可以帮你的？")

    while True:
        try:
            user_input = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if not user_input:
            continue
        if user_input.lower() == "quit":
            print("再见！")
            break
        if user_input.lower().startswith("switch "):
            new_id = user_input.split()[1]
            print(f"切换到: {get_employee(new_id)}")
            current_user = new_id
            history = []  # 切换身份清空历史
            continue

        response = chat(user_input, current_user, history)
        print(f"\n{response}")


if __name__ == "__main__":
    main()
