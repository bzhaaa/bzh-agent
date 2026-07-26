"""Agent 模式提醒和注入频率。"""

from mewcode.models import AgentMode
from mewcode.prompting.models import ReminderDetail

NORMAL_FULL = (
    "当前为 Normal Mode。可以使用当前提供的全部工具；持续调查、执行并验证，直到任务完成。"
    "编辑或覆盖已有文件前先读取当前内容；命令执行服从用户确认；失败时依据工具结果调整。"
)
PLAN_FULL = (
    "当前为 Plan Mode。只调查项目并形成可执行计划，不得修改文件或执行命令；"
    "只能使用当前提供的三个只读工具。即使用户要求直接执行，也必须保持只读。"
)
NORMAL_COMPACT = "当前为 Normal Mode；继续执行并验证，编辑已有文件前先读取。"
PLAN_COMPACT = "当前为 Plan Mode；保持只读，只调查并更新计划。"


class ReminderScheduler:
    """根据一次 Run 内的 1-based 迭代号选择提醒。"""

    def detail_for(self, iteration: int) -> ReminderDetail:
        if iteration < 1:
            raise ValueError("迭代号必须大于零。")
        return ReminderDetail.FULL if (iteration - 1) % 5 == 0 else ReminderDetail.COMPACT

    def build(self, mode: AgentMode, iteration: int) -> str:
        detail = self.detail_for(iteration)
        if mode == AgentMode.PLAN:
            return PLAN_FULL if detail == ReminderDetail.FULL else PLAN_COMPACT
        return NORMAL_FULL if detail == ReminderDetail.FULL else NORMAL_COMPACT
