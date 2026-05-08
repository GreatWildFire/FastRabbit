## 生图API调用文档
`
base_url:https://grsai.dakka.com.cn/v1/draw/nano-banana
api_key:sk-ee65775d6d654903a3ca60c4720787d0
请求方式:POST
响应方式:stream 或 回调接口
请求头Headers
{
  "Content-Type": "application/json",
  "Authorization": "Bearer apikey"
}
请求参数：
{
  "model": "nano-banana-fast",
  "prompt": "提示词",
  "aspectRatio": "auto",
  "imageSize": "1K",
  "urls": [
    "https://example.com/example.png"
  ],
  "webHook": "https://example.com/callback",
  "shutProgress": false
}

参数说明：
model（必填）
类型: string
示例: "nano-banana-fast"
描述:
支持模型: nano-banana-2
nano-banana-2-cl
nano-banana-2-4k-cl
nano-banana-fast
nano-banana
nano-banana-pro
nano-banana-pro-vt
nano-banana-pro-cl
nano-banana-pro-vip
nano-banana-pro-4k-vip

urls（选填）
类型: array
示例: ["https://example.com/example.png"]
描述:参考图URL or Base64

prompt（必填）
类型: string
示例: "一只可爱的猫咪在草地上玩耍"
描述:提示词

aspectRatio（选填）
类型: string
示例: "auto"
描述:输出图像比例,支持的比例:
auto
1:1
16:9
9:16
4:3
3:4
3:2
2:3
5:4
4:5
21:9
默认 auto
-
nano-banana-2
nano-banana-2-cl
nano-banana-2-4k-cl
额外支持比例:
1:4
4:1
1:8
8:1

imageSize（选填）
类型: string
示例: "1K"
描述:
支持模型：
nano-banana-2
nano-banana-2-cl(只支持1k，2k)
nano-banana-2-4k-cl(只支持4k)
nano-banana-pro
nano-banana-pro-vt
nano-banana-pro-cl
nano-banana-pro-vip(只支持1k，2k)
nano-banana-pro-4k-vip(只支持4k)
-
输出图像大小,支持的大小:
1K
2K
4K
默认 1K
-
注意：分辨率越高，生成时间越长

webHook（选填）
类型: string
示例: "https://your-webhook-url.com/callback"
描述:进度与结果的回调链接
接口默认以Stream流式响应进行回复
如果填了webHook，进度与结果则以Post请求回调地址的方式进行回复
请求头: Content-Type: application/json
-------
如果不使用回调，而使用轮询result接口方式获取结果，需要接口立即返回一个id
则webHook参数填"-1"，那么会立即返回一个id

shutProgress（选填）
类型: boolean
示例: false
描述:关闭进度回复，直接回复最终结果,建议搭配webHook使用
默认false
webHook结果
(请求后该结果会返回一个id，用于对应回调数据)
(使用流式响应请跳过该步骤)
复制
webHook结果参数说明
(使用流式响应请跳过该步骤)

code
类型: number
示例: 0
描述:状态码：0为成功

msg
类型: string
示例: "success"
描述:状态信息

data
类型: object
描述:数据

data.id
类型: object
示例: "f44bcf50-f2d0-4c26-a467-26f2014a771b"
描述:程序任务id，对应回调数据

响应参数 (JSON)
(流式响应与webHook响应的参数)
响应参数说明
id
类型: string
示例: "f44bcf50-f2d0-4c26-a467-26f2014a771b"
描述:Id (webHook回调可以用该id来对应数据)

results
类型: array
示例: [{"url": "https://example.com/generated-image.jpg", "content": "这是一只可爱的猫咪在草地上玩耍"}]
描述:结果

content: 回复内容
url: 图片URL(有效期为2小时)
progress
类型: number
示例: 100
描述:任务进度,0~100

status
类型: string
示例: "succeeded"
描述:任务状态
"running": 进行中
"succeeded": 成功
"failed": 失败

failure_reason
类型: string
示例: "error"
描述:失败原因
"output_moderation": 输出违规
"input_moderation": 输入违规
"error": 其他错误
------
提示：当触发"error"时，可尝试重新提交任务来确保系统稳定性。
error
类型: string
示例: "Invalid input parameters"
描述:失败详细信息
`