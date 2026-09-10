"""OpenAPI 必须能生成，且依赖注入不能被误判成查询参数。

这条测试挡住一类**测试跑不出来、但线上必炸**的问题：

- 在带 `from __future__ import annotations` 的模块里用局部变量构造
  `Depends(loader)`，注解会退化成字符串前向引用，FastAPI 解析失败后
  把依赖对象当成必填查询参数 —— 接口返回 422，而单元测试全绿。
- schema 里有未完全定义的模型时，`/docs` 与前端 SDK 生成会直接抛异常。
"""

from __future__ import annotations

import pytest

from backend.app.main import create_app

#: 这些名字是依赖注入的产物，绝不该出现在查询参数里。
INJECTED_NAMES = {"asset", "actor", "container", "assets", "service", "request", "response"}


@pytest.fixture(scope="module")
def spec() -> dict:
    return create_app().openapi()


def test_openapi_generates(spec: dict) -> None:
    assert len(spec["paths"]) > 40, "路由数量异常，可能有 router 没挂上"


@pytest.mark.parametrize("prefix", ["/api", "/v1"])
def test_expected_prefixes_present(spec: dict, prefix: str) -> None:
    paths = [path for path in spec["paths"] if path.startswith(prefix)]
    assert paths, f"{prefix} 下没有任何路由"


def test_no_injected_dependency_leaks_into_query(spec: dict) -> None:
    leaks: list[str] = []
    for path, methods in spec["paths"].items():
        for method, operation in methods.items():
            for parameter in operation.get("parameters", []):
                if parameter.get("in") == "query" and parameter["name"] in INJECTED_NAMES:
                    leaks.append(f"{method.upper()} {path} -> query.{parameter['name']}")
    assert not leaks, "依赖被当成查询参数，接口会 422：\n" + "\n".join(leaks)


def test_every_operation_has_a_response_schema(spec: dict) -> None:
    missing: list[str] = []
    for path, methods in spec["paths"].items():
        for method, operation in methods.items():
            if not operation.get("responses"):
                missing.append(f"{method.upper()} {path}")
    assert not missing, "缺少响应定义的接口：\n" + "\n".join(missing)
