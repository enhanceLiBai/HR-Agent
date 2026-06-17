"""工具注册与分发 —— 根据工具名分发到对应的执行函数。"""


def execute_tool(name: str, args: dict) -> str:
    """根据工具名分发到对应的执行函数。"""
    from tools.policy import search_policy
    from tools.leave import (
        query_leave_balance,
        create_leave_request,
        approve_leave,
        reject_leave,
        list_pending_approvals,
    )
    from tools.employee import get_employee, get_my_leave_history

    registry = {
        "search_policy":          lambda: search_policy(args["query"]),
        "query_leave_balance":    lambda: query_leave_balance(args["employee_id"], args["leave_type"]),
        "create_leave_request":   lambda: create_leave_request(args["employee_id"], args["leave_type"], args["start_date"], args["end_date"], args["reason"]),
        "approve_leave":          lambda: approve_leave(args["request_id"], args["approver_id"], args.get("comment", "")),
        "reject_leave":           lambda: reject_leave(args["request_id"], args["approver_id"], args["reason"]),
        "list_pending_approvals": lambda: list_pending_approvals(args["manager_id"]),
        "get_employee":           lambda: get_employee(args["employee_id"]),
        "get_my_leave_history":   lambda: get_my_leave_history(args["employee_id"], args.get("limit", 10)),
    }

    func = registry.get(name)
    if not func:
        return f"❌ 未知工具: {name}"
    try:
        return func()
    except Exception as e:
        return f"❌ 工具执行错误 ({name}): {str(e)}"
