import datetime
import time
import pyupbit

from alert_manager import AlertManager


class UpbitAutoTrader:
    def __init__(self):
        # 대상 코인
        self.ticker = "KRW-BTC"

        # Upbit 설정 객체 변수
        keys = self.get_key_info()
        self.access_key = keys["access_key"]
        self.secret_key = keys["secret_key"]
        self.upbit = pyupbit.Upbit(self.access_key, self.secret_key)

        # 알림 설정 객체 생성
        self.alert_manager = AlertManager()
        result = self.alert_manager.send_discord(
            "🔔 Upbit 변동성 돌파 자동매매 시스템이 시작되었습니다."
        )
        print(result)

        # 프로그램 제어 변수
        self.hold = False
        self.is_set_price = False
        self.buy_price = None
        self.target_price = None
        self.max_price = 0.0
        self.last_traded_date = None

        if not self.hold and not self.is_set_price:
            self.target_price = self.cal_target_price(self.ticker)
            self.is_set_price = True
            self.alert_manager.send_discord(
                f"✨ [장중 기동] 첫날 대기 목표가 즉시 설정 완료: {self.target_price:,.0f}원"
            )

        self.sync_account_state()

    def sync_account_state(self):
        try:
            # 1. 현재 보유 중인 비트코인 수량 조회
            btc_balance = self.upbit.get_balance(self.ticker)

            # 최소 주문 금액(5,000원) 이상의 가치가 계좌에 있다면 보유 중(hold)인 것으로 판단
            current_price = pyupbit.get_current_price(self.ticker)
            if btc_balance and current_price and (btc_balance * current_price > 5000):
                # 2. 업비트에서 평단가를 읽어와 복구
                avg_buy_price = self.upbit.get_avg_buy_price(self.ticker)

                self.hold = True
                self.buy_price = avg_buy_price
                self.max_price = (
                    avg_buy_price  # 재시작 직후이므로 평단가를 일단 최고가로 설정
                )
                self.is_set_price = True
                self.last_traded_date = datetime.datetime.now().date()

                print(
                    f"[서버 재시작] 기존 매수 상태 복구 완료 - 평단가: {self.buy_price}원"
                )
                self.alert_manager.send_discord(
                    f"♻️ [서버 재시작] 기존 보유 상태 복구 감지\n- 평단가: {self.buy_price:,.0f}원"
                )
            else:
                print("[서버 재시작] 보유 잔고 없음 - 정상 대기 상태로 시작합니다.")
                self.alert_manager.send_discord(
                    "[서버 재시작] 보유 잔고 없음 - 정상 대기 상태로 시작합니다."
                )

        except Exception as e:
            print(f"[서버 재시작] 계좌 동기화 실패 (5초 후 기본값으로 시작): {e}")
            time.sleep(5)

    # 목표가 계산 메소드
    def cal_target_price(self, ticker):
        df = pyupbit.get_ohlcv(ticker, "day")
        yesterday = df.iloc[-2]
        today = df.iloc[-1]
        yesterday_range = yesterday["high"] - yesterday["low"]
        target_price = today["open"] + yesterday_range * 0.4

        return target_price

    # Upbit API 키 값 가져오는 메소드
    def get_key_info(self):
        f = open("upbit.txt")
        lines = f.readlines()
        access_key = lines[0].strip()
        secret_key = lines[1].strip()
        f.close()
        keys = {"access_key": access_key, "secret_key": secret_key}

        return keys

    # 목표가 업데이트 조건 확인 메소드
    def is_time_to_update_target(self, now):
        return (
            now.hour == 9
            and now.minute == 0
            and not self.is_set_price
            and not self.hold
        )

    # 매수 가격 조건 확인 메소드
    def is_buy_price_signal_triggered(self, current_price, now):
        # 오늘 이미 매매한 이력이 없고, 목표가가 설정되었고, 미보유 상태일 때 가격 돌파 확인
        return (
            self.last_traded_date != now.date()
            and self.is_set_price
            and not self.hold
            and current_price >= self.target_price
        )

    # 매도 시간 조건 확인 메소드
    def is_sell_time_signal_triggered(self, now):
        return now.hour == 8 and now.minute == 59 and self.hold

    # 매도 가격 조건 확인 메소드
    def is_sell_trailing_stop_triggered(self, current_price):
        if not self.hold:
            return False

        if current_price > self.max_price:
            self.max_price = current_price

        trailing_stop_price = self.max_price * 0.98

        return current_price <= trailing_stop_price

    # 거래 체결 대기 메소드
    def wait_for_execution(self, order_uuid):
        while True:
            order_info = self.upbit.get_order(order_uuid)
            trades = order_info.get("trades", [])

            if trades:
                buy_price = float(trades[0]["funds"]) / float(trades[0]["volume"])
                return buy_price

            time.sleep(0.5)

    def run_auto_trader(self):
        while True:
            try:
                now = datetime.datetime.now()
                current_price = pyupbit.get_current_price(self.ticker)

                # API 호출 실패로 None이 반환된 경우 루프 넘김
                if current_price is None:
                    time.sleep(1)
                    continue

                # 09:00:00 목표가 갱신
                if self.is_time_to_update_target(now):
                    self.target_price = self.cal_target_price(self.ticker)
                    self.is_set_price = True
                    self.alert_manager.send_discord(
                        f"🎯 금일 목표가가 갱신되었습니다.\n- 목표가: {self.target_price:,.0f}원"
                    )

                # 1) 매수 - 목표가 달성
                elif self.is_buy_price_signal_triggered(current_price, now):
                    krw_balance = self.upbit.get_balance("KRW")

                    safe_buy_funds = krw_balance * 0.995

                    # 최소 주문 금액(5,000원) 이상일 때만 실행
                    if safe_buy_funds > 5000:
                        order_result = self.upbit.buy_market_order(
                            self.ticker, safe_buy_funds
                        )
                        self.buy_price = self.wait_for_execution(order_result["uuid"])
                        self.max_price = self.buy_price
                        self.hold = True
                        self.last_traded_date = now.date()  # 오늘 매수 완료 도장 쾅

                        self.alert_manager.send_discord(
                            f"🚀 매수 조건 달성 체결 완료\n- 매수가: {self.buy_price:,.0f}원"
                        )

                # 2) 매도 - 시간 만료
                elif self.is_sell_time_signal_triggered(now):
                    btc_balance = self.upbit.get_balance(self.ticker)
                    order_result = self.upbit.sell_market_order(
                        self.ticker, btc_balance
                    )
                    sell_price = self.wait_for_execution(order_result["uuid"])

                    # 8시 59분 하루 정산 브리핑 계산
                    profit_rate = ((sell_price - self.buy_price) / self.buy_price) * 100
                    self.alert_manager.send_discord(
                        f"⏱️ 08:59 장마감 타임아웃 전량 매도 및 정산\n"
                        f"- 진입 평단가: {self.buy_price:,.0f}원\n"
                        f"- 최종 매도가: {sell_price:,.0f}원\n"
                        f"- 금일 최종 수익률: {profit_rate:.2f}%"
                    )

                    self.is_set_price = False
                    self.hold = False

                # 3) 매도 - 손절가 (트레일링 스탑)
                elif self.is_sell_trailing_stop_triggered(current_price):
                    btc_balance = self.upbit.get_balance(self.ticker)
                    order_result = self.upbit.sell_market_order(
                        self.ticker, btc_balance
                    )
                    sell_price = self.wait_for_execution(order_result["uuid"])

                    # 트레일링 스탑 정산 브리핑 계산
                    profit_rate = ((sell_price - self.buy_price) / self.buy_price) * 100
                    self.alert_manager.send_discord(
                        f"🚨 최고가 대비 2% 하락 익절/손절(트레일링 스탑) 발동\n"
                        f"- 장중 최고가: {self.max_price:,.0f}원\n"
                        f"- 진입 평단가: {self.buy_price:,.0f}원\n"
                        f"- 최종 매도가: {sell_price:,.0f}원\n"
                        f"- 확정 수익률: {profit_rate:.2f}%"
                    )

                    self.hold = False

                time.sleep(1)

            except Exception as e:
                # 에러 발생 대기 후 재시도 (요청사항: 프린트와 동시에 디코드 알림 발송)
                print(f"에러 발생 대기 후 재시도: {e}")
                self.alert_manager.send_discord(
                    f"⚠️ 시스템 오류 발생 (5초 후 자동 재시도):\n```{e}```"
                )
                time.sleep(5)


if __name__ == "__main__":
    upbit_auto_trader = UpbitAutoTrader()
    upbit_auto_trader.run_auto_trader()
