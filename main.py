from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.event.filter import event_message_type, EventMessageType
from astrbot.api.all import Image 
from astrbot.api.star import Context, Star, register
from rapidocr_onnxruntime import RapidOCR
import cv2, os, re
from pyzbar.pyzbar import decode

@register("今日新闻", "egg", "60秒国内新闻", "1.0.0", "https://github.com/bbpn-cn/headline")
class HXPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        ocr = RapidOCR()
        self.user_states = {}  # 记录用户监听状态：{ (user_id, group_id): [消息列表] }

    @filter.command("hx")
    async def start_hx(self, event: AstrMessageEvent):
        """触发核销监听，使用方式：/hx"""
        key = (event.user_id, event.group_id or "private")
        self.user_states[key] = []  # 开始监听
        yield event.plain_result("📝 已进入核销模式，请发送三张图片")

    @event_message_type(EventMessageType.ALL)
    async def handle_hx_images(self, event: AstrMessageEvent):
        key = (event.user_id, event.group_id or "private")

        if key not in self.user_states:
            return  # 不在监听状态，跳过

        # 收集该用户的消息
        messages = event.get_messages()
        self.user_states[key].append(messages)

        # 检查是否已收集 3 条消息
        if len(self.user_states[key]) < 3:
            return

        # 合并这三条消息
        all_msgs = [msg for batch in self.user_states[key] for msg in batch]

        # 判断是否全为图片
        if all(isinstance(msg, Image) for msg in all_msgs):
            yield event.plain_result("✅ 核销成功，开始处理")
            await self.run_hx_action(event, all_msgs)
        else:
            yield event.plain_result("❌ 核销内容不规范，必须发送三张图片")

        # 无论成功失败都清理状态
        del self.user_states[key]

    async def run_hx_action(self, event, images: list):
        local_paths = []

        # 🔽 下载图片到本地
        for img in images:
            path = await img.convert_to_file_path()
            if not path or not os.path.exists(path):
                yield event.plain_result("❌ 图片下载失败")
                return
            local_paths.append(path)

        # ✅ 处理第一张图（OCR 提取手机号）
        ocr_result, _ = self.ocr(local_paths[0])
        phone = None
        for line in ocr_result:
            if "购号码" in line[1]:
                match = re.search(r'1\d{10}', line[1])
                if match:
                    phone = match.group()
                break
        if phone:
            yield event.plain_result(f"📱 提取手机号：{phone}")
        else:
            yield event.plain_result("❌ 未识别出手机号")

        # ✅ 处理第 2 和 3 张图（二维码识别）
        for i in [1, 2]:
            try:
                img_cv = cv2.imread(local_paths[i])
                gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
                resized = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_LINEAR)
                _, thresh = cv2.threshold(resized, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                qr_codes = decode(thresh)

                if qr_codes:
                    for qr in qr_codes:
                        content = qr.data.decode('utf-8')
                        yield event.plain_result(f"🔍 第{i+1}张二维码内容：{content}")
                else:
                    yield event.plain_result(f"❌ 第{i+1}张未识别到二维码")

            except Exception as e:
                yield event.plain_result(f"⚠️ 第{i+1}张识别出错：{str(e)}")

        # ✅ 可选：清理本地图片
        for path in local_paths:
            try:
                os.unlink(path)
            except Exception:
                pass