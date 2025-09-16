# azan_reminder_strict.py
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime, date
import threading
import time
import requests
import re
import pyautogui
import os
from plyer import notification

# ----------------------------
# تنظیم‌ها
# ----------------------------
API_URL = "https://prayer.aviny.com/api/prayertimes/11"
FETCH_INTERVAL_SECONDS = 30       # دریافت اوقات شرعی هر ۳۰ ثانیه
UI_UPDATE_INTERVAL = 1            # بروزرسانی UI هر ۱ ثانیه
NOTIFY_INTERVAL = 20              # فاصله نوتیف در ثانیه
LOCK_AFTER_NOTIF_COUNT = 5        # تعداد نوتیف قبل از فعال شدن موس و قفل
LOCK_MOUSE_DURATION = 60          # نگه داشتن موس در مرکز
TIME_REGEX = re.compile(r'\b([0-1]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?\b')

# ----------------------------
# کلاس حالت نماز
# ----------------------------
class PrayerState:
    def __init__(self, name, dt=None):
        self.name = name
        self.dt = dt
        self.notifying = False
        self.notif_count = 0
        self.last_notify = None
        self.read = False  # آیا نماز خوانده شده است؟

# ----------------------------
# دریافت اوقات شرعی
# ----------------------------
def fetch_prayers():
    try:
        r = requests.get(API_URL, timeout=10)
        times = [m.group(0) for m in TIME_REGEX.finditer(r.text)]
        today = date.today()

        def parse_time(t):
            for fmt in ("%H:%M:%S", "%H:%M"):
                try:
                    return datetime.combine(today, datetime.strptime(t, fmt).time())
                except:
                    continue
            return None

        def choose_range(hour_min, hour_max):
            candidates = [parse_time(t) for t in times if parse_time(t) and hour_min <= parse_time(t).hour <= hour_max]
            return candidates[0] if candidates else None

        prayers = {}
        prayers["Dhuhr"] = choose_range(10, 15)
        prayers["Maghrib"] = choose_range(16, 21)
        return prayers
    except Exception as e:
        print("خطا در دریافت اوقات شرعی:", e)
        return {}

# ----------------------------
# موس در مرکز صفحه
# ----------------------------
def lock_mouse_center(duration=LOCK_MOUSE_DURATION):
    screen_width, screen_height = pyautogui.size()
    center_x, center_y = screen_width // 2, screen_height // 2
    end_time = time.time() + duration
    while time.time() < end_time:
        pyautogui.moveTo(center_x, center_y, duration=0.1)
        time.sleep(0.1)

# ----------------------------
# کلاس اصلی UI
# ----------------------------
class AzanApp:
    def __init__(self, root):
        self.root = root
        root.title("یادآور اذان")
        root.geometry("500x400")
        root.resizable(False, False)

        style = ttk.Style()
        style.theme_use('clam')
        style.configure("Treeview.Heading", font=("Tahoma", 12, "bold"))
        style.configure("Treeview", font=("Tahoma", 11), rowheight=28)
        style.configure("TButton", font=("Tahoma", 11))
        style.configure("TLabel", font=("Tahoma", 12))

        frm = ttk.Frame(root, padding=10)
        frm.pack(fill="both", expand=True)

        header = ttk.Label(frm, text="اذان ظهر و مغرب", font=("Tahoma", 14, "bold"))
        header.pack(anchor="center", pady=(0, 10))

        self.tree = ttk.Treeview(frm, columns=("time","status"), show="headings", height=5)
        self.tree.heading("time", text="زمان")
        self.tree.heading("status", text="وضعیت")
        self.tree.column("time", width=160, anchor="center")
        self.tree.column("status", width=200, anchor="center")
        self.tree.pack(fill="x", pady=(0,10))

        btn_frame = ttk.Frame(frm)
        btn_frame.pack(fill="x", pady=(0,10))
        ttk.Button(btn_frame, text="بروز رسانی دستی", command=self.fetch_once).pack(side="left")
        ttk.Button(btn_frame, text="خاموش اعلان‌ها", command=self.stop_notifications).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="روشن اعلان‌ها", command=self.start_notifications).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="حالت سخت‌گیرانه", command=self.toggle_strict_mode).pack(side="left", padx=5)

        ttk.Label(frm, text="لاگ:", font=("Tahoma", 12)).pack(anchor="w")
        self.log = tk.Text(frm, height=8, state="disabled", font=("Tahoma",11))
        self.log.pack(fill="both", expand=True)

        self.prayers = {}
        self.notifications_enabled = True
        self.strict_mode = False
        self.first_run_checked = False
        self._stop = False

        self.fetch_once()
        threading.Thread(target=self.fetch_loop, daemon=True).start()
        self.ui_updater()

    # ----------------------------
    # ثبت لاگ
    # ----------------------------
    def log_msg(self, txt):
        self.log.configure(state="normal")
        self.log.insert("end", f"{datetime.now().strftime('%H:%M:%S')} - {txt}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    # ----------------------------
    # دریافت اوقات شرعی
    # ----------------------------
    def fetch_once(self):
        times = fetch_prayers()
        for name, dt in times.items():
            if dt:
                if name not in self.prayers:
                    self.prayers[name] = PrayerState(name, dt)
                else:
                    self.prayers[name].dt = dt
        self.refresh_treeview()
        self.log_msg("اوقات شرعی بروز شد.")

    def fetch_loop(self):
        while not self._stop:
            self.fetch_once()
            time.sleep(FETCH_INTERVAL_SECONDS)

    # ----------------------------
    # بروزرسانی جدول
    # ----------------------------
    def refresh_treeview(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        for name in ["Dhuhr","Maghrib"]:
            st = self.prayers.get(name)
            tstr = st.dt.strftime("%H:%M:%S") if st and st.dt else "---"
            status = self.get_status_text(st) if st else "---"
            self.tree.insert("", "end", iid=name, values=(f"{name} - {tstr}", status))

    def get_status_text(self, st):
        if not st or not st.dt:
            return "---"
        now = datetime.now()
        diff = st.dt - now
        if diff.total_seconds() > 0:
            hrs = int(diff.total_seconds()//3600)
            mins = int((diff.total_seconds()%3600)//60)
            return f"{hrs}س {mins}د مانده"
        else:
            passed = now - st.dt
            hrs = int(passed.total_seconds()//3600)
            mins = int((passed.total_seconds()%3600)//60)
            return f"{hrs}س {mins}د گذشته"

    # ----------------------------
    # نزدیکترین نماز
    # ----------------------------
    def nearest_prayer(self):
        now = datetime.now()
        nearest = None
        nearest_diff = None
        for st in self.prayers.values():
            if st.dt:
                diff = abs((st.dt - now).total_seconds())
                if nearest is None or diff < nearest_diff:
                    nearest = st
                    nearest_diff = diff
        return nearest

    # ----------------------------
    # آپدیت UI و نوتیف
    # ----------------------------
    def ui_updater(self):
        try:
            st = self.nearest_prayer()
            if st:
                self.tree.set(st.name, "status", self.get_status_text(st))

                # بررسی اولین ران شدن برنامه
                if not self.first_run_checked:
                    self.ask_prayer_done(st)
                    self.first_run_checked = True

                if self.notifications_enabled and st.dt and datetime.now() >= st.dt:
                    if not st.read:
                        if st.notif_count < LOCK_AFTER_NOTIF_COUNT:
                            if st.last_notify is None or (datetime.now() - st.last_notify).total_seconds() >= NOTIFY_INTERVAL:
                                threading.Thread(target=self.send_notification, args=(st,), daemon=True).start()
                        elif st.notif_count >= LOCK_AFTER_NOTIF_COUNT and self.strict_mode:
                            # موس در مرکز
                            threading.Thread(target=lock_mouse_center, args=(LOCK_MOUSE_DURATION,), daemon=True).start()
                            # ویندوز قفل
                            threading.Thread(target=self.lock_windows, daemon=True).start()
        except Exception as e:
            self.log_msg(f"خطا در آپدیت UI: {e}")
        finally:
            if not self._stop:
                self.root.after(UI_UPDATE_INTERVAL*1000, self.ui_updater)

    # ----------------------------
    # نوتیف
    # ----------------------------
    def send_notification(self, st):
        notification.notify(
            title="یادآور اذان",
            message=f"وقت {st.name} رسیده!",
            timeout=8
        )
        st.notifying = True
        st.notif_count += 1
        st.last_notify = datetime.now()
        self.log_msg(f"اعلان {st.name} ارسال شد ({st.notif_count}/{LOCK_AFTER_NOTIF_COUNT})")

    # ----------------------------
    # قفل ویندوز
    # ----------------------------
    def lock_windows(self):
        self.log_msg("سیستم قفل می‌شود! برای نماز بلند شوید.")
        time.sleep(3)
        try:
            os.system("rundll32.exe user32.dll,LockWorkStation")
        except Exception as e:
            self.log_msg(f"خطا در قفل سیستم: {e}")

    # ----------------------------
    # نوتیف/اعلان‌ها
    # ----------------------------
    def stop_notifications(self):
        self.notifications_enabled = False
        for st in self.prayers.values():
            st.notif_count = 0
        self.log_msg("اعلان‌ها خاموش شدند.")

    def start_notifications(self):
        self.notifications_enabled = True
        for st in self.prayers.values():
            st.notif_count = 0
        self.log_msg("اعلان‌ها روشن شدند.")

    # ----------------------------
    # حالت سخت‌گیرانه
    # ----------------------------
    def toggle_strict_mode(self):
        msg = ("حالت سخت‌گیرانه فعال می‌شود.\n"
               "- اگر نماز را نخوانده باشید، موس در مرکز صفحه قرار می‌گیرد.\n"
               "- پس از ۵ دقیقه سیستم قفل خواهد شد.\n"
               "- آیا می‌خواهید ادامه دهید؟\n\n"
               "https://github.com/YourGitHubProfile")
        if messagebox.askyesno("حالت سخت‌گیرانه", msg):
            self.strict_mode = True
            self.log_msg("حالت سخت‌گیرانه فعال شد.")
        else:
            self.strict_mode = False
            self.log_msg("حالت سخت‌گیرانه غیرفعال ماند.")

    # ----------------------------
    # سوال اولین بار اجرا
    # ----------------------------
    def ask_prayer_done(self, st):
        if st.dt and datetime.now() >= st.dt:
            res = messagebox.askyesno("سوال نماز", f"نماز {st.name} را خوانده‌اید؟")
            if res:
                st.read = True
                self.log_msg(f"نماز {st.name} خوانده شد.")
            else:
                st.read = False
                self.log_msg(f"نماز {st.name} خوانده نشده، نوتیف ادامه می‌یابد.")

    # ----------------------------
    # متوقف کردن
    # ----------------------------
    def stop(self):
        self._stop = True

# ----------------------------
# اجرا
# ----------------------------
if __name__ == "__main__":
    root = tk.Tk()
    app = AzanApp(root)
    try:
        root.mainloop()
    finally:
        app.stop()
