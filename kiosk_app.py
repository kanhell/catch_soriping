#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
캐치 소리핑 - 모니터 UI (Tkinter)
사용법/자동 실행 설정은 README.md 참고.
"""

import subprocess
import threading
import queue
from datetime import datetime, timezone
import tkinter as tk
from tkinter import ttk

import firebase_admin
from firebase_admin import credentials, firestore

from config import FIREBASE_KEY_PATH
from bt_wifi_setup import connect_wifi
from logger_setup import get_logger

logger = get_logger("kiosk_app")

CATEGORY_COLOR = {
    "emergency": "#ff3b30",
    "fire": "#ff3b30",
    "maintenance": "#2563eb",
    "general": "#64748b",
}

FONT_FAMILY = "Malgun Gothic"


# ============================================================
# Firebase 초기화 (한 번만)
# ============================================================

if not firebase_admin._apps:
    cred = credentials.Certificate(FIREBASE_KEY_PATH)
    firebase_admin.initialize_app(cred)
db = firestore.client()


# ============================================================
# 와이파이 관련 헬퍼
# ============================================================

def get_current_ssid():
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "active,ssid", "device", "wifi"],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.strip().split("\n"):
            if line.startswith("yes:"):
                return line.split(":", 1)[1]
    except Exception as e:
        logger.error(f"현재 와이파이 확인 실패: {e}")
    return None


def scan_wifi_networks():
    try:
        subprocess.run(["sudo", "nmcli", "device", "wifi", "rescan"], capture_output=True, timeout=15)
        result = subprocess.run(
            ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list"],
            capture_output=True, text=True, timeout=15,
        )
        networks = {}
        for line in result.stdout.strip().split("\n"):
            parts = line.split(":")
            if len(parts) < 3 or not parts[0]:
                continue
            ssid, signal, security = parts[0], parts[1], parts[2]
            try:
                signal = int(signal)
            except ValueError:
                signal = 0
            if ssid not in networks or networks[ssid]["signal"] < signal:
                networks[ssid] = {"ssid": ssid, "signal": signal, "security": security or "오픈"}
        return sorted(networks.values(), key=lambda n: -n["signal"])
    except Exception as e:
        logger.error(f"와이파이 스캔 실패: {e}")
        return []


# ============================================================
# 화면 키보드 (터치용 - 와이파이 비밀번호 입력에 사용)
# ============================================================

class Keyboard(tk.Frame):
    ROWS = ["1234567890", "qwertyuiop", "asdfghjkl", "zxcvbnm"]
    SYMBOLS = "-_.@!#*"

    def __init__(self, parent, target_var):
        super().__init__(parent, bg="#e5e7eb")
        self.target_var = target_var
        self.shift = False
        self.key_buttons = []
        self._build()

    def _build(self):
        for row in self.ROWS:
            row_frame = tk.Frame(self, bg="#e5e7eb")
            row_frame.pack(pady=2)
            for ch in row:
                btn = tk.Button(
                    row_frame, text=ch, width=3, font=(FONT_FAMILY, 12),
                    relief="flat", bg="white",
                    command=lambda c=ch: self._press(c),
                )
                btn.pack(side="left", padx=2)
                self.key_buttons.append(btn)

        sym_frame = tk.Frame(self, bg="#e5e7eb")
        sym_frame.pack(pady=2)
        for ch in self.SYMBOLS:
            tk.Button(
                sym_frame, text=ch, width=3, font=(FONT_FAMILY, 12),
                relief="flat", bg="white", command=lambda c=ch: self._press(c),
            ).pack(side="left", padx=2)

        bottom = tk.Frame(self, bg="#e5e7eb")
        bottom.pack(pady=4)

        tk.Button(
            bottom, text="⇧ 대문자", width=8, font=(FONT_FAMILY, 12), relief="flat",
            bg="white", command=self._toggle_shift,
        ).pack(side="left", padx=2)
        tk.Button(
            bottom, text="space", width=16, font=(FONT_FAMILY, 12), relief="flat",
            bg="white", command=lambda: self._press(" "),
        ).pack(side="left", padx=2)
        tk.Button(
            bottom, text="⌫ 지우기", width=8, font=(FONT_FAMILY, 12), relief="flat",
            bg="white", command=self._backspace,
        ).pack(side="left", padx=2)

    def _press(self, ch):
        if self.shift:
            ch = ch.upper()
        self.target_var.set(self.target_var.get() + ch)

    def _backspace(self):
        self.target_var.set(self.target_var.get()[:-1])

    def _toggle_shift(self):
        self.shift = not self.shift
        for btn in self.key_buttons:
            c = btn["text"]
            btn.config(text=c.upper() if self.shift else c.lower())


# ============================================================
# 메인 앱
# ============================================================

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("아파트 실시간 방송")
        self.geometry("1024x600")
        self.configure(bg="white")
        self.attributes("-fullscreen", True)
        self.bind("<Escape>", lambda e: self.attributes("-fullscreen", False))

        container = tk.Frame(self, bg="white")
        container.pack(fill="both", expand=True)

        self.frames = {}
        for F in (MainPage, SettingsPage):
            frame = F(container, self)
            self.frames[F.__name__] = frame
            frame.place(relwidth=1, relheight=1)

        self.show_frame("MainPage")

    def show_frame(self, name):
        self.frames[name].tkraise()
        on_show = getattr(self.frames[name], "on_show", None)
        if on_show:
            on_show()


# ============================================================
# 페이지 1: 방송 목록 (메인 페이지)
# ============================================================

class MainPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent, bg="white")
        self.controller = controller
        self.queue = queue.Queue()
        self.rows = []

        header = tk.Frame(self, bg="#f4f5f7", height=80)
        header.pack(fill="x")
        header.pack_propagate(False)

        tk.Label(
            header, text="아파트 실시간 방송", bg="#f4f5f7",
            font=(FONT_FAMILY, 22, "bold"), fg="#111318",
        ).pack(side="left", padx=28)

        tk.Button(
            header, text="기기 연결 설정 ⚙", font=(FONT_FAMILY, 12, "bold"),
            bg="#e5e7eb", fg="#111318", relief="flat", padx=14, pady=8,
            command=lambda: controller.show_frame("SettingsPage"),
        ).pack(side="right", padx=20)

        # 네트워크 미연결 안내 배너 (평소엔 숨김)
        self.network_banner = tk.Label(
            self, text="⚠ 네트워크에 연결해주세요", bg="#fff3cd", fg="#92400e",
            font=(FONT_FAMILY, 13, "bold"), pady=10,
        )

        # 스크롤 가능한 목록 영역
        list_container = tk.Frame(self, bg="white")
        list_container.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(list_container, bg="white", highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_container, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg="white")

        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.inner, anchor="nw", width=1024)
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.empty_label = tk.Label(
            self.inner, text="불러오는 중...", bg="white", fg="#8b8f98", font=(FONT_FAMILY, 14)
        )
        self.empty_label.pack(pady=60)

        self._start_listener()
        self.after(300, self._poll_queue)
        self._check_wifi_loop()

    # --- Firestore 실시간 목록 ---

    def _start_listener(self):
        def on_snapshot(col_snapshot, changes, read_time):
            logger.info(f"방송 목록 갱신: {len(col_snapshot)}건")
            self.queue.put(("docs", list(col_snapshot)))

        try:
            query = db.collection("announcements").order_by("timestamp", direction=firestore.Query.DESCENDING)
            self.watch = query.on_snapshot(on_snapshot)
            logger.info("방송 목록 리스너 등록 완료. 응답 대기 중...")
        except Exception as e:
            logger.error(f"방송 목록 리스너 등록 실패: {e}")

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "docs":
                    self._render(payload)
                elif kind == "wifi_status":
                    self._update_network_banner(payload)
        except queue.Empty:
            pass
        self.after(300, self._poll_queue)

    def _render(self, docs):
        for widget in self.inner.winfo_children():
            widget.destroy()
        self.rows = []

        if not docs:
            tk.Label(
                self.inner, text="등록된 방송이 없습니다.", bg="white", fg="#8b8f98", font=(FONT_FAMILY, 14)
            ).pack(pady=60)
            return

        # 서버 정렬(DESCENDING)에 더해 클라이언트에서도 한 번 더 최신순 정렬 (안전장치)
        epoch = datetime.min.replace(tzinfo=timezone.utc)
        docs = sorted(docs, key=lambda d: d.to_dict().get("timestamp") or epoch, reverse=True)

        for doc in docs:
            data = doc.to_dict()
            self._add_row(doc.id, data)

    def _add_row(self, doc_id, data):
        color = CATEGORY_COLOR.get(data.get("category"), CATEGORY_COLOR["general"])
        is_read = data.get("isRead", True)

        row = tk.Frame(self.inner, bg="white")
        row.pack(fill="x")

        top = tk.Frame(row, bg="white", cursor="hand2")
        top.pack(fill="x", padx=28, pady=18)

        left = tk.Frame(top, bg="white")
        left.pack(side="left", fill="x", expand=True)

        title_row = tk.Frame(left, bg="white")
        title_row.pack(anchor="w", fill="x")

        dot_widget = None
        if not is_read:
            dot_widget = tk.Canvas(title_row, width=10, height=10, bg="white", highlightthickness=0)
            dot_widget.create_oval(1, 1, 9, 9, fill="#ff3b30", outline="")
            dot_widget.pack(side="left", padx=(0, 8), pady=(4, 0))

        tk.Label(
            title_row, text=data.get("title", "[안내]"), bg="white", fg=color,
            font=(FONT_FAMILY, 16, "bold"), anchor="w",
        ).pack(side="left")

        ts = data.get("timestamp")
        date_str = ts.strftime("%m/%d %H:%M") if ts else ""
        tk.Label(
            left, text=date_str, bg="white", fg="#8b8f98", font=(FONT_FAMILY, 11), anchor="w"
        ).pack(anchor="w", pady=(4, 0))

        chevron = tk.Label(top, text="▾", bg="white", fg="#4b4f58", font=(FONT_FAMILY, 14))
        chevron.pack(side="right")

        body = tk.Frame(row, bg="white")
        full_ts = ts.strftime("%Y년 %m월 %d일 %H시 %M분 %S초") if ts else ""

        body_label = tk.Label(
            body, text=data.get("text", ""), bg="white", fg="#111318",
            font=(FONT_FAMILY, 13), justify="left", anchor="w", wraplength=920,
        )
        body_label.pack(anchor="w", padx=28, pady=(0, 4))

        tk.Label(
            body, text=full_ts, bg="white", fg="#8b8f98", font=(FONT_FAMILY, 10), anchor="w"
        ).pack(anchor="w", padx=28, pady=(0, 8))

        delete_btn = tk.Label(
            body, text="🗑  삭제", bg="white", fg="#ff3b30", font=(FONT_FAMILY, 12, "bold"), cursor="hand2"
        )
        delete_btn.pack(anchor="e", padx=28, pady=(0, 18))
        delete_btn.bind("<Button-1>", lambda e: self._confirm_delete(doc_id, data.get("title", "이 방송")))

        divider = tk.Frame(row, bg="#e2e4e8", height=1)
        divider.pack(fill="x")

        state = {"open": False, "read_marked": False}

        def toggle(event=None):
            state["open"] = not state["open"]
            if state["open"]:
                body.pack(fill="x")
                chevron.config(text="▴")
                if not is_read and not state["read_marked"]:
                    state["read_marked"] = True
                    if dot_widget:
                        dot_widget.destroy()
                    threading.Thread(target=lambda: self._mark_read(doc_id), daemon=True).start()
            else:
                body.pack_forget()
                chevron.config(text="▾")

        def bind_recursive(widget):
            widget.bind("<Button-1>", toggle)
            for child in widget.winfo_children():
                bind_recursive(child)

        top.bind("<Button-1>", toggle)
        for child in top.winfo_children():
            bind_recursive(child)

        self.rows.append(row)

    # --- 읽음 처리 ---

    def _mark_read(self, doc_id):
        try:
            db.collection("announcements").document(doc_id).update({"isRead": True})
            logger.info(f"읽음 처리됨 (id={doc_id})")
        except Exception as e:
            logger.error(f"읽음 처리 실패 (id={doc_id}): {e}")

    # --- 삭제 ---

    def _confirm_delete(self, doc_id, title):
        dialog = tk.Toplevel(self)
        dialog.title("삭제 확인")
        dialog.geometry("360x180")
        dialog.configure(bg="white")
        dialog.transient(self)

        tk.Label(dialog, text="이 방송을 삭제할까요?", bg="white", font=(FONT_FAMILY, 15, "bold")).pack(pady=(28, 6))
        tk.Label(dialog, text=title, bg="white", fg="#8b8f98", font=(FONT_FAMILY, 11), wraplength=300).pack()

        btn_row = tk.Frame(dialog, bg="white")
        btn_row.pack(pady=20)

        def do_delete():
            threading.Thread(target=lambda: self._delete_doc(doc_id), daemon=True).start()
            dialog.destroy()

        tk.Button(
            btn_row, text="취소", font=(FONT_FAMILY, 12), bg="#e5e7eb", relief="flat",
            padx=16, pady=6, command=dialog.destroy,
        ).pack(side="left", padx=8)
        tk.Button(
            btn_row, text="삭제", font=(FONT_FAMILY, 12, "bold"), bg="#ff3b30", fg="white",
            relief="flat", padx=16, pady=6, command=do_delete,
        ).pack(side="left", padx=8)

        dialog.update_idletasks()
        dialog.grab_set()

    def _delete_doc(self, doc_id):
        try:
            db.collection("announcements").document(doc_id).delete()
            logger.info(f"방송 삭제됨 (id={doc_id})")
        except Exception as e:
            logger.error(f"방송 삭제 실패 (id={doc_id}): {e}")

    # --- 네트워크 상태 배너 ---

    def _check_wifi_loop(self):
        def worker():
            connected = get_current_ssid() is not None
            self.queue.put(("wifi_status", connected))

        threading.Thread(target=worker, daemon=True).start()
        self.after(5000, self._check_wifi_loop)

    def _update_network_banner(self, connected):
        if connected:
            self.network_banner.pack_forget()
        else:
            self.network_banner.pack(fill="x", after=self.winfo_children()[0])


# ============================================================
# 페이지 2: 기기 연결 설정 (와이파이)
# ============================================================

class SettingsPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent, bg="white")
        self.controller = controller
        self.queue = queue.Queue()

        header = tk.Frame(self, bg="#f4f5f7", height=80)
        header.pack(fill="x")
        header.pack_propagate(False)

        tk.Button(
            header, text="← 방송 목록", font=(FONT_FAMILY, 12, "bold"),
            bg="#e5e7eb", fg="#111318", relief="flat", padx=14, pady=8,
            command=lambda: controller.show_frame("MainPage"),
        ).pack(side="left", padx=20)

        tk.Label(
            header, text="기기 연결 설정", bg="#f4f5f7",
            font=(FONT_FAMILY, 22, "bold"), fg="#111318",
        ).pack(side="left", padx=8)

        status_frame = tk.Frame(self, bg="white")
        status_frame.pack(fill="x", padx=28, pady=(22, 10))

        tk.Label(status_frame, text="현재 연결", bg="white", fg="#8b8f98", font=(FONT_FAMILY, 12)).pack(anchor="w")
        self.status_var = tk.StringVar(value="확인 중...")
        tk.Label(
            status_frame, textvariable=self.status_var, bg="white", fg="#111318",
            font=(FONT_FAMILY, 16, "bold"), anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        list_header = tk.Frame(self, bg="white")
        list_header.pack(fill="x", padx=28, pady=(16, 6))

        tk.Label(list_header, text="주변 와이파이", bg="white", fg="#111318", font=(FONT_FAMILY, 14, "bold")).pack(side="left")
        tk.Button(
            list_header, text="새로고침", font=(FONT_FAMILY, 11),
            bg="#e5e7eb", fg="#111318", relief="flat", padx=10, pady=4,
            command=self.refresh_networks,
        ).pack(side="right")

        list_container = tk.Frame(self, bg="white")
        list_container.pack(fill="both", expand=True, padx=28, pady=(0, 10))

        self.canvas = tk.Canvas(list_container, bg="white", highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_container, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg="white")

        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.inner, anchor="nw", width=960)
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.after(200, self._poll_queue)

    def on_show(self):
        self.refresh_status()
        self.refresh_networks()

    def refresh_status(self):
        def worker():
            ssid = get_current_ssid()
            self.queue.put(("status", ssid))
        threading.Thread(target=worker, daemon=True).start()

    def refresh_networks(self):
        for widget in self.inner.winfo_children():
            widget.destroy()
        tk.Label(self.inner, text="검색 중...", bg="white", fg="#8b8f98", font=(FONT_FAMILY, 13)).pack(pady=30)

        def worker():
            networks = scan_wifi_networks()
            self.queue.put(("networks", networks))
        threading.Thread(target=worker, daemon=True).start()

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "status":
                    self.status_var.set(payload if payload else "연결 안 됨")
                elif kind == "networks":
                    self._render_networks(payload)
                elif kind == "connect_result":
                    ok, msg = payload
                    self._show_result(ok, msg)
                elif kind == "close_dialog":
                    payload.destroy()
        except queue.Empty:
            pass
        self.after(200, self._poll_queue)

    def _render_networks(self, networks):
        for widget in self.inner.winfo_children():
            widget.destroy()

        if not networks:
            tk.Label(self.inner, text="검색된 와이파이가 없습니다.", bg="white", fg="#8b8f98", font=(FONT_FAMILY, 13)).pack(pady=30)
            return

        for net in networks:
            row = tk.Frame(self.inner, bg="white", cursor="hand2")
            row.pack(fill="x", pady=6)

            tk.Label(row, text=net["ssid"], bg="white", fg="#111318", font=(FONT_FAMILY, 14), anchor="w").pack(side="left", padx=(4, 0))
            tk.Label(row, text=f'{net["security"]}  ·  신호 {net["signal"]}%', bg="white", fg="#8b8f98", font=(FONT_FAMILY, 11)).pack(side="right", padx=(0, 4))

            divider = tk.Frame(self.inner, bg="#e2e4e8", height=1)
            divider.pack(fill="x")

            def on_click(event, ssid=net["ssid"], security=net["security"]):
                self._open_password_dialog(ssid, security)

            row.bind("<Button-1>", on_click)
            for child in row.winfo_children():
                child.bind("<Button-1>", on_click)

    def _open_password_dialog(self, ssid, security):
        dialog = tk.Toplevel(self)
        dialog.title(f"{ssid} 연결")
        dialog.geometry("460x460")
        dialog.configure(bg="white")
        dialog.transient(self)

        tk.Label(dialog, text=ssid, bg="white", font=(FONT_FAMILY, 16, "bold")).pack(pady=(16, 6))

        is_open = security in ("", "오픈", "--")
        pw_var = tk.StringVar()

        if not is_open:
            tk.Label(dialog, text="비밀번호", bg="white", font=(FONT_FAMILY, 12)).pack(pady=(6, 4))
            entry = tk.Entry(dialog, textvariable=pw_var, show="*", font=(FONT_FAMILY, 14), justify="center")
            entry.pack(ipady=6, padx=40, fill="x")

            Keyboard(dialog, pw_var).pack(pady=(12, 0))

        status_label = tk.Label(dialog, text="", bg="white", fg="#8b8f98", font=(FONT_FAMILY, 11))
        status_label.pack(pady=(10, 0))

        def do_connect():
            status_label.config(text="연결 중...")
            password = pw_var.get()

            def worker():
                ok, msg = connect_wifi(ssid, password)
                self.queue.put(("connect_result", (ok, msg)))
                self.queue.put(("close_dialog", dialog))

            threading.Thread(target=worker, daemon=True).start()

        tk.Button(
            dialog, text="연결", font=(FONT_FAMILY, 13, "bold"),
            bg="#2563eb", fg="white", relief="flat", padx=20, pady=8,
            command=do_connect,
        ).pack(pady=10)

        dialog.update_idletasks()
        dialog.grab_set()
        if not is_open:
            entry.focus()

    def _show_result(self, ok, msg):
        dialog = tk.Toplevel(self)
        dialog.geometry("380x160")
        dialog.configure(bg="white")
        dialog.transient(self)

        color = "#2563eb" if ok else "#ff3b30"
        title = "연결 성공" if ok else "연결 실패"

        tk.Label(dialog, text=title, bg="white", fg=color, font=(FONT_FAMILY, 16, "bold")).pack(pady=(24, 8))
        tk.Label(dialog, text=msg, bg="white", fg="#111318", font=(FONT_FAMILY, 12), wraplength=320).pack(pady=(0, 16))
        tk.Button(dialog, text="확인", command=dialog.destroy, relief="flat", bg="#e5e7eb", padx=20, pady=6).pack()

        dialog.update_idletasks()
        dialog.grab_set()

        if ok:
            self.refresh_status()


if __name__ == "__main__":
    app = App()
    app.mainloop()
