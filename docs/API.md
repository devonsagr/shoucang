# API 接入

默认地址 `http://127.0.0.1:8766`；完整现行接口表在本机 `/docs`，标准 schema 在 `/openapi.json`。响应版本以 `/api/health` 为准。

写请求必须带 `Content-Type: application/json` 和 `X-Local-Request: 1`。浏览器写请求仅接受本站 Origin；服务默认只对本机开放，不能把这个请求头当成远程身份认证。JSON 中不要传密码、整库文件或与当前任务无关的笔记。

## 收集材料

```http
POST /api/materials
X-Local-Request: 1
Content-Type: application/json

{"url":"https://example.org/an-article","origin":"link"}
```

`origin` 为 `favorite` 或 `link`。通常仅提供链接即可排队；也可明确提供 `text`、`title`、`subtitles`、`subtitle_format`、`subtitle_source` 和 `language`。响应含材料 ID；重复来源返回 `duplicate: true`。永久删除的来源返回 `retired: true` 并跳过，不应据此假称新材料已抓取成功。只有本人明确选择重新收集时使用 `recollect_deleted: true`。

- `GET /api/materials`：按平台、主题、处理/采集状态、来源和全文查询；返回条目和当前范围计数。
- `GET /api/materials/{id}`：原文、字幕来源、分段、批注、历史与当前任务。`reading_preview` 仅供界面筛选，不属于处理输入或持久化摘要。
- `POST /api/materials/{id}/retry`：重试未完整内容；`{"refresh":true}` 主动刷新旧正文，批注和历史保留。
- `POST /api/accounts/{platform}/login`：`{"action":"open","url":"该平台的原文链接"}` 打开同平台验证页；`url` 可省略，默认登录或收藏入口。本人完成后用 `{"action":"save"}` 保存；小黑盒页面仍有可见验证时拒绝保存。`GET /api/accounts` 的 `access_required` 表示仍需本人处理。
- `POST /api/import`：TXT 转换后的 URL 项目或含 url/origin/text 的 JSON 数组。
- `POST /api/favorites`：`{"platform":"heybox"}` 等，读取本人已保存登录的平台收藏页。响应任务 ID；`resume_job_id` 仅续读上次断点。

默认只为新来源排队正文。明确传 `repair_incomplete: true` 时，同时为本次清单返回的既有失败、部分完成或暂停材料排队补齐；不重采已完整材料、不恢复删除记录，不补采清单外条目。`repair_queued` 是排队数，不是成功数。续读保留原任务的此选项。小黑盒通过网页重新触发原生分页并跳过已登记ID，进度里的offset用于追踪，不伪造签名直接跳过网页前几页。

小黑盒优先消费网站的专用收藏接口响应，`transport=heybox_favorites_api`、`endpoint` 和 `checkpoint.offset` 在任务进度中可追溯；不会保存请求Cookie或签名参数。只接受该接口实际返回的帖子ID，校验分页连续性和账号一致性；列表摘要不是完整原文。短页另核对一次返回的下一offset，验证拒绝就停止。未取得接口时只有专用收藏容器兼容回退，且不会标成全部成功。
- `GET /api/jobs`、`POST /api/jobs/{id}/stop`：任务状态、进度、明确末尾或中断原因。列表任务结束不代表每条正文/图片/字幕都成功。

## 知识库路径

```http
PUT /api/obsidian
X-Local-Request: 1
Content-Type: application/json

{
  "vault": "D:/Notes/ExampleVault",
  "paths": {
    "archive": "收集/原文",
    "callable": "一级/调用资料",
    "digest": "一级/待消化",
    "trash": "回收/材料",
    "materials": "参考材料"
  },
  "targets": ["学习/AI", "音乐/专辑"]
}
```

根目录需为可访问的本机绝对路径；留空使用项目 `data/knowledge-base`。阶段目录是根内普通相对路径，原始存档、两种第一层和回收站不可互相包含；不能指向隐藏配置目录、上级目录或盘符。`materials` 是各主题下材料专区的相对名称。常用目标只用于入口提示，实际目标仍可明确填写更细的主题路径。保存配置不会搬动或写入已有材料；旧预览失效。

`GET /api/settings` 不返回密钥；`GET /api/first-layer/folders`、`GET /api/materials/{id}/processing-paths` 和 `/api/storage` 返回配置及具体位置。

## 批注、预览与确认

```http
PUT /api/materials/{id}/notes
X-Local-Request: 1
Content-Type: application/json

{"notes":"以后写作时引用这一方法，暂时不作个人判断。","revision":3}
```

保存时传读取到的修订号，迟到更新不能覆盖新修改。第一层分流示例：

```http
POST /api/materials/{id}/push-preview
X-Local-Request: 1
Content-Type: application/json

{"destination":"obsidian","complete_processing":false,"shelf_output":{"stage":"callable"}}
```

另一方向为 `digest`。预览返回 `id`、`hash`、具体 `destination`、Markdown 与附件清单，不立即写文件。本人审查后：

```http
POST /api/pushes/{preview-id}/confirm
X-Local-Request: 1
Content-Type: application/json

{"hash":"<预览返回的原始hash>"}
```

同一确认重复调用会返回幂等结果；原文、批注、目录或关联笔记已变时需要新预览。第一层与原始来源独立，可经 `/api/first-layer` 查询。`GET /api/first-layer/organization-prompt` 返回结合当前根和阶段目录的后续整理背景；只供交接，不构成自动写入授权。

`destination` 也支持 `markdown`、`knowledge`、`todo`。这三项目前生成本机 outbox 的 Markdown/JSON/附件，**不会创建外部待办、发消息或调用某个任务系统**。下游工具可按确认回执和 `idempotency_key` 消费；接入某个外部工具时需另行实现适配及写入确认。

删除为可恢复回收：`DELETE /api/materials/{id}`；恢复为 `POST /api/materials/{id}/restore`。永久删除需 `/purge` 的当前 revision 和确认文字；批量接口同样逐条检查修订、文件归属和哈希。不要绕过预览/确认直接操作数据库或知识库文件。

`POST /api/materials/batch-actions` 的 `action` 支持 `trash/restore/purge/retry`，每请求1–100个 `{id,revision}`；界面把更大选择分批提交。重试返回逐条 `job_id` 与 `kind`（`images`或`collect`），完整条目为 `skipped`，已在队列为 `duplicate`；这些是排队回执，不是采集成功。重试不能写第一层快照或回收条目。`/api/accounts` 的 `access_required` 表示上次平台拒绝尚待本人处理，即使已保存Cookie也不表示权限可用；保存或导入最新单平台状态后允许下一次读取核验。
