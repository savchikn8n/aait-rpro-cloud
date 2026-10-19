"""Уши и глаза для видеоуроков Skill Camp.

Для каждого work/LNN.mp4:
  work/LNN.wav            — аудио 16 кГц (временное)
  work/LNN.segments.json  — распознанная речь (faster-whisper large-v3, GPU) с таймкодами
  work/LNN.txt            — стенограмма «[мм:сс] текст»
  work/LNN_frames/        — ключевые кадры (смена сцены + не реже раза в 25 с) с подписью времени
  work/LNN_sheets/        — контактные листы 3x3 кадров (их просматривает Claude)

Запуск: python agent/iitb/transcribe.py [номера через запятую]
"""
import glob
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
W = os.path.join(HERE, "work")


def cuda_paths():
    """cuBLAS/cuDNN из pip-пакетов nvidia-* не в PATH — подключаем вручную."""
    import site
    for sp in site.getsitepackages():
        for sub in ("cublas", "cudnn", "cuda_runtime"):
            d = os.path.join(sp, "nvidia", sub, "bin")
            if os.path.isdir(d):
                os.add_dll_directory(d)
                os.environ["PATH"] = d + os.pathsep + os.environ["PATH"]


def ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def mmss(t):
    t = int(t)
    return "%02d:%02d" % (t // 60, t % 60)


def audio(n):
    mp4, wav = os.path.join(W, "L%02d.mp4" % n), os.path.join(W, "L%02d.wav" % n)
    if not os.path.exists(wav):
        subprocess.run([ffmpeg(), "-y", "-loglevel", "error", "-i", mp4, "-vn", "-ac", "1", "-ar", "16000", wav], check=True)
    return wav


def speech(n, model):
    seg_path = os.path.join(W, "L%02d.segments.json" % n)
    if os.path.exists(seg_path):
        return
    wav = audio(n)
    segs, info = model.transcribe(
        wav, language="ru", vad_filter=True, beam_size=5, condition_on_previous_text=False,
        initial_prompt="Урок по программе Р-Про (Рациональное производство, Visual Components): цифровое производство, роботы, симуляция, бережливое производство.",
    )
    out = [{"s": round(s.start, 1), "e": round(s.end, 1), "t": s.text.strip()} for s in segs]
    json.dump({"duration": info.duration, "segments": out}, open(seg_path, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    with open(os.path.join(W, "L%02d.txt" % n), "w", encoding="utf-8") as f:
        for s in out:
            f.write("[%s] %s\n" % (mmss(s["s"]), s["t"]))
    os.remove(wav)


def frames(n):
    import cv2
    mp4 = os.path.join(W, "L%02d.mp4" % n)
    fd = os.path.join(W, "L%02d_frames" % n)
    sd = os.path.join(W, "L%02d_sheets" % n)
    if os.path.isdir(sd) and os.listdir(sd):
        return
    os.makedirs(fd, exist_ok=True)
    os.makedirs(sd, exist_ok=True)
    cap = cv2.VideoCapture(mp4)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = int(fps * 1.0)  # сэмпл раз в секунду
    prev, last_kept, kept = None, -999, []
    for i in range(0, total, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, fr = cap.read()
        if not ok:
            break
        t = i / fps
        small = cv2.cvtColor(cv2.resize(fr, (96, 54)), cv2.COLOR_BGR2GRAY)
        diff = 0 if prev is None else float(cv2.absdiff(small, prev).mean())
        prev = small
        # смена сцены (порог) или давно не было кадра; не чаще раза в 6 с
        if (diff > 9 and t - last_kept >= 6) or t - last_kept >= 25:
            fr2 = cv2.resize(fr, (800, int(800 * fr.shape[0] / fr.shape[1])))
            cv2.rectangle(fr2, (0, 0), (90, 26), (0, 0, 0), -1)
            cv2.putText(fr2, mmss(t), (6, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            p = os.path.join(fd, "%05d.jpg" % int(t))
            cv2.imwrite(p, fr2, [cv2.IMWRITE_JPEG_QUALITY, 80])
            kept.append(p)
            last_kept = t
    cap.release()
    import numpy as np
    for k in range(0, len(kept), 4):  # листы 2x2: текст интерфейса остаётся читаемым
        imgs = [cv2.imread(p) for p in kept[k:k + 4]]
        h, w = imgs[0].shape[:2]
        while len(imgs) < 4:
            imgs.append(np.zeros((h, w, 3), np.uint8))
        sheet = np.vstack([np.hstack(imgs[:2]), np.hstack(imgs[2:])])
        cv2.imwrite(os.path.join(sd, "sheet_%03d.jpg" % (k // 4 + 1)), sheet, [cv2.IMWRITE_JPEG_QUALITY, 82])
    print("L%02d: кадров %d, листов %d" % (n, len(kept), (len(kept) + 3) // 4), flush=True)


def main():
    nums = [int(x) for x in sys.argv[1].split(",")] if len(sys.argv) > 1 else sorted(
        int(os.path.basename(p)[1:3]) for p in glob.glob(os.path.join(W, "L??.mp4")))
    cuda_paths()
    from faster_whisper import WhisperModel
    model = WhisperModel("large-v3", device="cuda", compute_type="float16")
    for n in nums:
        if not os.path.exists(os.path.join(W, "L%02d.mp4" % n)):
            continue
        speech(n, model)
        print("L%02d: речь готова" % n, flush=True)
        frames(n)


if __name__ == "__main__":
    main()
