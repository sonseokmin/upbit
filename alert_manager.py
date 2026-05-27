import os
import pandas as pd
import requests

from config.constatns import ALERT_CONFIG_PATH


class AlertManager:
    def __init__(self):
        self.discord_url = None

        self.load_config()

    def load_config(self):
        if not os.path.exists(ALERT_CONFIG_PATH):
            return False

        try:
            df = pd.read_excel(ALERT_CONFIG_PATH).fillna("")

            discord_url = str(df.get("Discord", [""])[0]).strip()

            # 유효한 값 있을 때만 할당
            if discord_url and discord_url.lower() != "nan":
                self.discord_url = discord_url

            return True

        except Exception:
            return False

    def send_discord(self, msg):
        """디스코드 알림 전송"""
        if not self.discord_url:
            return "⚠️ 디스코드 설정 없음"

        try:
            response = requests.post(
                self.discord_url,
                json={"content": msg},
                timeout=5,
            )
            return "🔔 디스코드 전송 확인" if response.ok else "⚠️ 디스코드 전송 실패"
        except:
            return "⚠️ 디스코드 통신 오류"


if __name__ == "__main__":
    alert_manager = AlertManager()

    print(alert_manager.send_discord("테스트"))
