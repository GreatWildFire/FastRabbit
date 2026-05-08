**request参考代码**
`
# request参考代码
import os
import time
# Install SDK:  pip install 'volcengine-python-sdk[ark]'
from volcenginesdkarkruntime import Ark 

client = Ark(
    # The base URL for model invocation
    base_url='https://ark.cn-beijing.volces.com/api/v3',
    # Get API Key：https://console.volcengine.com/ark/region:ark+cn-beijing/apikey
    api_key=os.environ.get("ARK_API_KEY"),
)

if __name__ == "__main__":
    print("----- create request -----")
    create_result = client.content_generation.tasks.create(
        model="doubao-seedance-2-0-260128", # Replace with Model ID 
        content=[
            {
                "type": "text",
                "text": "全程使用视频1的第一视角构图，全程使用音频1作为背景音乐。第一人称视角果茶宣传广告，seedance牌「苹苹安安」苹果果茶限定款；首帧为图片1，你的手摘下一颗带晨露的阿克苏红苹果，轻脆的苹果碰撞声；2-4 秒：快速切镜，你的手将苹果块投入雪克杯，加入冰块与茶底，用力摇晃，冰块碰撞声与摇晃声卡点轻快鼓点，背景音：「鲜切现摇」；4-6 秒：第一人称成品特写，分层果茶倒入透明杯，你的手轻挤奶盖在顶部铺展，在杯身贴上粉红包标，镜头拉近看奶盖与果茶的分层纹理；6-8 秒：第一人称手持举杯，你将图片2中的果茶举到镜头前（模拟递到观众面前的视角），杯身标签清晰可见，背景音「来一口鲜爽」，尾帧定格为图片2。背景声音统一为女生音色。",
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": "https://ark-project.tos-cn-beijing.volces.com/doc_image/r2v_tea_pic1.jpg"
                },
                "role": "reference_image",
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": "https://ark-project.tos-cn-beijing.volces.com/doc_image/r2v_tea_pic2.jpg"
                },
                "role": "reference_image",
            },
            {
                "type": "video_url",
                "video_url": {
                    "url": "https://ark-project.tos-cn-beijing.volces.com/doc_video/r2v_tea_video1.mp4"
                },
                "role": "reference_video",
            },
            {
                "type": "audio_url",
                "audio_url": {
                    "url": "https://ark-project.tos-cn-beijing.volces.com/doc_audio/r2v_tea_audio1.mp3"
                },
                "role": "reference_audio",
            },
        ],
        generate_audio=True,
        ratio="16:9",
        duration=11,
        watermark=True,
    )
    print(create_result)


    # Polling query section
    print("----- polling task status -----")
    task_id = create_result.id
    while True:
        get_result = client.content_generation.tasks.get(task_id=task_id)
        status = get_result.status
        if status == "succeeded":
            print("----- task succeeded -----")
            print(get_result)
            break
        elif status == "failed":
            print("----- task failed -----")
            print(f"Error: {get_result.error}")
            break
        else:
            print(f"Current status: {status}, Retrying after 30 seconds...")
            time.sleep(30)
`

**response参考**
`
# response
----- create request -----
ContentGenerationTaskID(id='cgt-20260414114820-*****')
----- polling task status -----
Current status: running, Retrying after 30 seconds...
Current status: running, Retrying after 30 seconds...
Current status: running, Retrying after 30 seconds...
...
----- task succeeded -----
ContentGenerationTask(id='cgt-20260414114820-*****', model='doubao-seedance-2-0-260128', status='succeeded', error=None, content=Content(video_url='', last_frame_url=None, file_url=None), usage=Usage(completion_tokens=411300, total_tokens=411300), subdivisionlevel=None, fileformat=None, frames=None, framespersecond=24, created_at=1776138520, updated_at=1776139219, seed=33608, revised_prompt=None, service_tier='default', execution_expires_after=172800, generate_audio=True, duration=11, ratio='16:9', resolution='720p', draft=False, draft_task_id=None)
`


请求参数 
请求体

---
model string  
您需要调用的模型的 ID （Model ID），开通模型服务，并查询 Model ID 。
您也可通过 Endpoint ID 来调用模型，获得限流、计费类型（前付费/后付费）、运行状态查询、监控、安全等高级能力，可参考获取 Endpoint ID。

---
content object[]  
输入给模型，生成视频的信息，支持文本、图片、音频、视频、样片任务 ID。
注意
seedance 2.0 系列模型不支持直接上传含有真人人脸的参考图/视频。为了便利创作者对肖像的使用，平台推出了以下解决方案，详情参见 教程。
- 支持使用部分模型的含人脸原始产物作为输入素材
- 支持使用预置虚拟人像作为输入素材
- 支持使用已授权真人素材作为输入
支持以下几种组合：
- 文本
- 文本（可选）+ 图片
- 文本（可选）+ 视频
- 文本（可选）+ 图片 + 音频
- 文本（可选）+ 图片 + 视频
- 文本（可选）+ 视频 + 音频
- 文本（可选）+ 图片 + 视频 + 音频
- 样片任务 ID：样片指使用 seedance 模型成功生成的样片视频，模型可基于样片生成高质量正式视频。
 

---
callback_url string 
填写本次生成任务结果的回调通知地址。当视频生成任务有状态变化时，方舟将向此地址推送 POST 请求。
回调请求内容结构与查询任务API的返回体一致。
回调返回的 status 包括以下状态：
- queued：排队中。
- running：任务运行中。
- succeeded： 任务成功。（如发送失败，即5秒内没有接收到成功发送的信息，回调三次）
- failed：任务失败。（如发送失败，即5秒内没有接收到成功发送的信息，回调三次）
- expired：任务超时，即任务处于运行中或排队中状态超过过期时间。可通过 execution_expires_after 字段设置过期时间。

---
return_last_frame boolean 默认值 false
- true：返回生成视频的尾帧图像。设置为 true 后，可通过 查询视频生成任务接口 获取视频的尾帧图像。尾帧图像的格式为 png，宽高像素值与生成的视频保持一致，无水印。
使用该参数可实现生成多个连续视频：以上一个生成视频的尾帧作为下一个视频任务的首帧，快速生成多个连续视频，调用示例详见 教程。
- false：不返回生成视频的尾帧图像。

---
service_tier string 默认值 default
不支持修改已提交任务的服务等级
seedance 2.0 & 2.0 fast 不支持离线推理
指定处理本次请求的服务等级类型，枚举值：
- default：在线推理模式，RPM 和并发数配额较低（详见 模型列表），适合对推理时效性要求较高的场景。
- flex：离线推理模式，TPD 配额更高（详见 模型列表），价格为在线推理的 50%， 适合对推理时延要求不高的场景。

---
execution_expires_after integer 默认值 172800
任务超时阈值。指定任务提交后的过期时间（单位：秒），从 created at 时间戳开始计算。默认值 172800 秒，即 48 小时。取值范围：[3600，259200]。
不论使用哪种 service_tier，都建议根据业务场景设置合适的超时时间。超过该时间后任务会被自动终止，并标记为expired状态。

---
generate_audio boolean 默认值 true
仅 seedance 2.0 & 2.0 fast、seedance 1.5 pro 支持
控制生成的视频是否包含与画面同步的声音。
- true：模型输出的视频包含同步音频。模型会基于文本提示词与视觉内容，自动生成与之匹配的人声、音效及背景音乐。建议将对话部分置于双引号内，以优化音频生成效果。例如：男人叫住女人说：“你记住，以后不可以用手指指月亮。”
- false：模型输出的视频为无声视频。
注意
生成的有声视频均为单声道，和传入的音频声道数无关。

---
draft boolean 默认值 false
仅 seedance 1.5 pro 支持
控制是否开启样片模式。阅读文档 获取使用教程和注意事项。
- true：开启样片模式，生成一段预览视频，快速验证场景结构、镜头调度、主体动作与 prompt 意图是否符合预期。消耗 token 数较正常视频更少，使用成本更低。
- false：关闭样片模式，正常生成一段视频。
说明
开启样片模式后，将使用 480p 分辨率生成 Draft 视频（使用其他分辨率会报错），不支持返回尾帧功能，不支持离线推理功能。

---
toolsnew object[] 
仅 seedance 2.0 & 2.0 fast 支持
配置模型要调用的工具。
 

---
safety_identifiernew string
终端用户的唯一标识符，用于协助平台检测您的应用中可能违反火山方舟使用政策的用户。该标识符为英文字符串，需保证对单个用户固定且唯一，长度不超过 64 个字符。推荐传入对用户名、用户 ID 或邮箱进行哈希处理后生成的字符串，避免泄露用户隐私信息。

---
部分参数升级说明
- 对于 resolution、ratio、duration、frames、seed、camera_fixed、watermark 参数，平台升级了参数传入方式，示例如下。所有模型依然兼容支持旧方式。
- 不同模型，可能对应支持不同的参数与取值，详见 输出视频格式。当输入的参数或取值不符合所选的模型时，该参数将被忽略或触发报错：
  - 新方式：在 request body 中直接传入参数。此方式为强校验，若参数填写错误，模型会返回错误提示。 
  - 旧方式：在文本提示词后追加 --[parameters]。此方式为弱校验，若参数填写错误，该参数将被忽略或触发报错。
 
 

---
resolution  string 
seedance 2.0 & 2.0 fast、seedance 1.5 pro、seedance 1.0 lite 默认值：720p
seedance 1.0 pro & pro-fast 默认值：1080p
视频分辨率，枚举值：
- 480p
- 720p
- 1080p：seedance 1.0 lite 参考图场景、seedance 2.0 fast 不支持

---
ratio string 
seedance 2.0 & 2.0 fast、seedance 1.5 pro 默认值为 adaptive
seedance 1.0 lite 参考图场景默认值为 16:9
其他模型：文生视频默认值 16:9，图生视频默认值 adaptive
生成视频的宽高比例。不同宽高比对应的宽高像素值见下方表格。
- 16:9 
- 4:3
- 1:1
- 3:4
- 9:16
- 21:9
- adaptive：根据输入自动选择最合适的宽高比（详见下文说明）
adaptive 适配规则
当配置 ratio 为 adaptive 时，模型会根据生成场景自动适配宽高比；实际生成的视频宽高比可通过 查询视频生成任务 API 返回的 ratio 字段获取。
支持模型：
- seedance 2.0 & 2.0 fast、seedance 1.5 Pro 支持
- 其他模型仅图生视频场景支持，注意 seedance 1.0 lite 参考图场景不支持。
取值规则：
- 文生视频：根据输入的提示词，智能选择最合适的宽高比。
- 首帧 / 首尾帧生视频：根据上传的首帧图片比例，自动选择最接近的宽高比。
- 多模态参考生视频：根据用户提示词意图判断，如果是首帧生视频/编辑视频/延长视频，以该图片/视频为准选择最接近的宽高比；否则，以传入的第一个媒体文件为准（优先级：视频＞图片）选择最接近的宽高比。
 

---
duration integer 默认值 5 
duration 和 frames 二选一即可，frames 的优先级高于 duration。如果您希望生成整数秒的视频，建议指定 duration。
生成视频时长，仅支持整数，单位：秒。
- seedance 1.0 pro、seedance 1.0 pro fast、seedance 1.0 lite: [2, 12] s。
- seedance 1.5 pro: [4,12] 或设置为-1
- seedance 2.0 & 2.0 fast:  [4,15] 或设置为-1
注意
seedance 2.0 & 2.0 fast、seedance 1.5 pro 支持两种配置方法
- 指定具体时长：支持有效范围内的任一整数。
- 智能指定：设置为 -1，表示由模型在有效范围内自主选择合适的视频长度（整数秒）。实际生成视频的时长可通过 查询视频生成任务 API 返回的 duration 字段获取。注意视频时长与计费相关，请谨慎设置。

---
frames integer 
seedance 2.0 & 2.0 fast、seedance 1.5 pro 暂不支持
duration 和 frames 二选一即可，frames 的优先级高于 duration。如果您希望生成小数秒的视频，建议指定 frames。
生成视频的帧数。通过指定帧数，可以灵活控制生成视频的长度，生成小数秒的视频。
由于 frames 的取值限制，仅能支持有限小数秒，您需要根据公式推算最接近的帧数。
- 计算公式：帧数 = 时长 × 帧率（24）。
- 取值范围：支持 [29, 289] 区间内所有满足 25 + 4n 格式的整数值，其中 n 为正整数。
例如：假设需要生成 2.4 秒的视频，帧数=2.4×24=57.6。由于 frames 不支持 57.6，此时您只能选择一个最接近的值。根据 25+4n 计算出最接近的帧数为 57，实际生成的视频为 57/24=2.375 秒。

---
seed integer 默认值 -1 
种子整数，用于控制生成内容的随机性。
取值范围：[-1, 2^32-1]之间的整数。
注意
- 相同的请求下，模型收到不同的seed值，如：不指定seed值或令seed取值为-1（会使用随机数替代）、或手动变更seed值，将生成不同的结果。
- 相同的请求下，模型收到相同的seed值，会生成类似的结果，但不保证完全一致。

---
camera_fixed boolean 默认值 false 
参考图场景不支持，seedance 2.0 & 2.0 fast 暂不支持
是否固定摄像头。枚举值：
- true：固定摄像头。平台会在用户提示词中追加固定摄像头，实际效果不保证。
- false：不固定摄像头。

---
watermark boolean 默认值 false 
生成视频是否包含水印。枚举值：
- false：不含水印。
- true：含有水印。

---
响应参数
跳转 请求参数
id string
视频生成任务 ID 。仅保存 7 天（从 created at 时间戳开始计算），超时后将自动清除。
- 设置"draft": true，为 Draft 视频任务 ID。
- 设置 "draft": false，为正常视频任务 ID。
创建视频生成任务为异步接口，获取 ID 后，需要通过 查询视频生成任务 API 来查询视频生成任务的状态。任务成功后，会输出生成视频的video_url。