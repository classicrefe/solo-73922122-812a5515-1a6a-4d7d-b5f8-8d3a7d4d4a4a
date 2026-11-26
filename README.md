# 同传接线规划服务

会议试音时, 音控录入**原声语种、现有接线、要锁定的监听源**, 服务算出**每个译席应接哪一路信号**、哪些语种**停供**, 可以直接照着接线。

## 接线规则

- 最多录入 **16 个译席**; 各席**输出语种互异**, 并自报能听懂哪些语种;
- 每个供声席**只接一路**自己听得懂的信号; 同一路信号**可供多席**监听;
- 从原声数起, 每路译声**最多经过两席(含发声席)**: 直取原声为一级, 听一级译声为二级, 二级译声不再供别人听;
- **锁定**监听源的译席必须照接并供声; 锁定之间无法同时满足时, **只报冲突**(HTTP 409), 不出方案;
- 优化目标: 先让**供声语种数最多**, 再让**要拆掉的原接线最少**(并列时少改动、少接力)。

## 启动

```bash
docker compose up --build
# 服务监听 http://localhost:8000 , 健康检查 GET /health , 交互文档 /docs
```

本地开发(不用 Docker):

```bash
pip install -r requirements.txt -r requirements-dev.txt
uvicorn app.main:app --reload
pytest                 # 跑关键接线情形的测试
```

## API

### `POST /plan`

请求体:

| 字段 | 说明 |
|---|---|
| `floor_language` | 原声语种 |
| `booths[]` | 译席: `id`、`output_language`(互异)、`understands[]`(能听懂的语种) |
| `existing[]` | 现有接线: `booth` + `source`(现接信号语种, 每席至多一条) |
| `locks[]` | 要锁定的监听源: `booth` + `source`(每席至多一条) |

`source` 用**语种**标识信号: 等于原声语种 = 接原声; 等于某席输出语种 = 接该席输出。

响应(200):

| 字段 | 说明 |
|---|---|
| `assignments[]` | 每席应接的信号: `source_kind`(`floor`/`booth`/`none`)、`source_language`、`source_booth`、`depth`(1=直取原声, 2=听一级译声, 0=未接)、`kept_existing` |
| `supplied_languages` | 供声语种(已最多) |
| `unsupplied_languages` | **停供语种**: 方案中未供声的译席输出语种 |
| `kept_connections` / `removed_connections` | 保留的 / **要拆掉的原接线**(已最少) |
| `summary` | 计数汇总 |

冲突(409): 只报冲突, 不出方案 —— `detail.conflicts[]` 列出每处冲突的译席、锁定源和原因
(听不懂锁定源 / 锁定源不存在 / 源席只能处二级、再供就超两席 / 源席自身被锁成二级 / 不能监听自己输出)。

录入不合法(422): 译席编号或输出语种重复、超过 16 席、输出语种等于原声、接线指向未录入的译席、同一席多条接线。

## 可试用的请求

启动服务后直接执行(`examples/` 目录已附请求体):

```bash
# 1) 基本方案: A 直取原声出英语, B 听 A 出法语; D 只听得懂法语(二级信号) -> 韩语停供
curl -s -X POST http://localhost:8000/plan -H 'Content-Type: application/json' \
  -d @examples/01_basic.json | python3 -m json.tool

# 2) 锁定照接: B 被锁定听 A 的英语, 必须照接并供声
curl -s -X POST http://localhost:8000/plan -H 'Content-Type: application/json' \
  -d @examples/02_locked.json | python3 -m json.tool

# 3) 锁定冲突: D 被锁定听 B 的法语, 但 B 听不懂原声、法语必是二级译声 -> 409 只报冲突
curl -s -X POST http://localhost:8000/plan -H 'Content-Type: application/json' \
  -d @examples/03_conflict.json | python3 -m json.tool
```

手写一个:

```bash
curl -s -X POST http://localhost:8000/plan -H 'Content-Type: application/json' -d '{
  "floor_language": "ja",
  "booths": [
    {"id": "A", "output_language": "en", "understands": ["ja"]},
    {"id": "B", "output_language": "fr", "understands": ["ja", "en"]},
    {"id": "C", "output_language": "de", "understands": ["ja"]}
  ],
  "existing": [{"booth": "B", "source": "en"}],
  "locks": []
}'
# B 听得懂原声、原接线是听 A: 没有别人依赖法语时, B 会降到二级保住原接线(拆 0 条)
```

## 目录结构

```
app/main.py     FastAPI 入口(POST /plan, GET /health)
app/models.py   录入模型与校验(16 席上限、输出语种互异等)
app/solver.py   求解器: 供声最多 -> 拆线最少(枚举降级组合取最优)
tests/          关键接线情形的单元测试与 API 测试
examples/       可直接 POST 的示例请求体
Dockerfile / docker-compose.yml
```
