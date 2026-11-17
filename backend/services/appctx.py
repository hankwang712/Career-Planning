"""进程内的 Flask 应用引用。

后台线程没有请求上下文，拿不到 current_app；server.py 创建应用后调用 bind()，
需要在线程里访问 app.logger / app.extensions 的模块通过 get_app() 取得它。
"""
_app = None


def bind(app):
    global _app
    _app = app


def get_app():
    if _app is None:
        raise RuntimeError("Flask 应用尚未创建")
    return _app
