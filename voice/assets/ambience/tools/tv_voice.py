import asyncio, sys, wave
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[4]))
from voice import dashscope_ws as ds
TEXT = ("下面是今天傍晚到明天白天的天气情况。本市今天夜里多云，偏北风三到四级，最低气温十二度。"
        "明天白天多云转晴，最高气温二十一度，早晚温差比较大，出门的朋友注意适当添加衣物。"
        "未来三天，全市以晴到多云天气为主，空气质量良到轻度污染，市民朋友外出时可以佩戴口罩。"
        "另外，这几天正是秋收秋种的关键时期，各地要抓住有利天气，做好农业生产安排。"
        "接下来请看一组本周的城市生活提示。最近早晚气温偏低，老年朋友晨练时间可以适当推迟。")
async def main():
    pcm = b""
    async for c in ds.synthesize(TEXT, voice="longanhuan", model="cosyvoice-v3-flash", sample_rate=24000):
        pcm += c
    with wave.open("tv_voice.wav", "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(pcm)
    print(len(TEXT), len(pcm) / 48000)
asyncio.run(main())
