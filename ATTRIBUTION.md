# DealDesk 开源致谢与协议说明

DealDesk 为 vertciti 自研代码（前后端均为独立重写，未复制任何第三方代码）。
开发过程中参考了以下开源项目的**功能形态、指标口径与工作流思想**，特此致谢：

| 项目 | 作者 | License | 参考内容 |
|---|---|---|---|
| Rental-Property-Deal-Analyzer | berkcankapusuzoglu | MIT | 20+ 指标口径、14 分制打分卡形态、回报四支柱、敏感性 what-if 表、FastAPI+静态前端架构 |
| rental-deal-calculator | onyxaholguin-cyber | MIT | 费用口径约定（维修/CapEx 按租金、管理费按实收）、纯函数计算+单元测试方法 |
| cre-agent-skills | ahacker-1 | Apache-2.0 | 商业核保工作流（rent roll→NOI 重算→DSCR→租约摘要→IC memo 结构） |
| re-pe-acquisition | rubyh218 | MIT | 按资产类别拆独立引擎、测试钉住 headline 数字、Pydantic 严格 schema |

- MIT License：https://opensource.org/licenses/MIT
- Apache License 2.0：https://www.apache.org/licenses/LICENSE-2.0

以下无 license 仓库**仅作逻辑参考、零代码复制**（其中数学公式为公有领域标准公式，
实现为 clean-room 重写）：ronnytiburcio/creative-finance-deal-structurer（wrap/subject-to
并行测算逻辑）、gmlesher/rental-property-calculator（分级思想）、stanjdev/realyzer（产品形态参考）。

详细学习记录为内部工作笔记，不随仓库发布。
