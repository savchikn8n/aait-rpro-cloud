"""Скачивание видео и PDF уроков Skill Camp (iitb.ru/for-students) в agent/iitb/work/.

Файлы лежат открыто в wp-content/uploads; список взят со страницы в авторизованном Chrome.
Запуск: python agent/iitb/fetch_media.py [--only 1,2,3]
"""
import os
import sys
import subprocess

BASE = "https://iitb.ru/wp-content/uploads/"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "work")

# номер урока -> (видео, pdf)
LESSONS = {
    1: ("2025/09/1-urok.mp4", "2025/09/zadanie-1.pdf"),
    2: ("2025/09/2-urok.mp4", "2025/09/zadanie-2.pdf"),
    3: ("2025/09/3-urok.mp4", "2025/09/zadanie-3.pdf"),
    4: ("2025/09/4-urok.mp4", "2025/09/zadanie-4.pdf"),
    5: ("2025/09/5-urok.mp4", "2025/09/zadanie-5.pdf"),
    6: ("2025/10/urok-6.mp4", "2025/09/zadanie-6.pdf"),
    7: ("2025/09/7-urok.mp4", "2025/09/zadanie-7.pdf"),
    8: ("2025/09/urok-8.mp4", "2025/09/zadanie-8.pdf"),
    9: ("2025/09/urok-9.mp4", "2025/09/zadanie-9.pdf"),
    10: ("2025/09/urok-10.mp4", "2025/09/zadanie-10.pdf"),
    11: ("2025/09/urok-111.mp4", "2025/09/zadanie-11-1.pdf"),
    12: ("2025/09/urok-122.mp4", "2025/09/zadanie-12.pdf"),
    13: ("2025/09/urok-131.mp4", "2025/09/zadanie-13.pdf"),
    14: ("2025/09/urok-141.mp4", "2025/09/zadanie-14.pdf"),
    15: ("2025/09/urok-151.mp4", "2025/09/zadanie-15.pdf"),
    16: ("2025/09/urok-161.mp4", "2025/09/zadanie-16.pdf"),
    18: ("2026/02/lss.mp4", None),
}


def fetch(rel, name):
    dst = os.path.join(OUT, name)
    if os.path.exists(dst) and os.path.getsize(dst) > 1000:
        return dst
    # python-SSL ломается о корпоративную подмену сертификатов; curl (schannel) работает
    subprocess.run(["curl", "-sSL", "--ssl-no-revoke", "--fail", "-o", dst + ".part", BASE + rel], check=True)
    os.replace(dst + ".part", dst)
    return dst


def main():
    only = None
    if "--only" in sys.argv:
        only = {int(x) for x in sys.argv[sys.argv.index("--only") + 1].split(",")}
    os.makedirs(OUT, exist_ok=True)
    for n, (v, p) in LESSONS.items():
        if only and n not in only:
            continue
        for rel, name in ((v, "L%02d.mp4" % n), (p, "L%02d.pdf" % n)):
            if not rel:
                continue
            p_ = fetch(rel, name)
            print(name, os.path.getsize(p_) // 1024, "КБ", flush=True)


if __name__ == "__main__":
    main()
