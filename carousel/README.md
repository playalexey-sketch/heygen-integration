# Карусели

Стандарт оформления и драматургии описан в **[STANDARD.md](STANDARD.md)** — читать перед любой новой каруселью.

## Структура

```
carousel/
├── STANDARD.md                 # мастер-промт: правила для всех каруселей
├── engine.py                   # движок (стандарт зашит здесь)
├── slides_ty_sleduyushiy.py    # контент карусели «Ты следующий?»
├── bg/                         # фоны
├── fonts/                      # Roboto
└── out/                        # готовые слайды
```

## Готовая карусель «Ты следующий?»

8 слайдов 1080×1350: `out/slide_1.png` … `out/slide_8.png`
Общее превью: `out/preview_all.jpg`
Архив: `out/karusel_ty_sleduyushiy.zip`

## Запуск

```bash
pip install pillow
python3 carousel/slides_ty_sleduyushiy.py
```

## Новая карусель

Копируешь `slides_ty_sleduyushiy.py`, меняешь список `SLIDES` и запускаешь —
номера слайдов, отсутствие нижних подписей, авто-подгон кегля и случайный
микро-призыв на последнем слайде применяются автоматически.
