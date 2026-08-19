# Brand Factory OS — Как запустить 1 файлом

## Вариант 1: Один файл Python (самый простой, кроссплатформенный)
```bash
python3 BrandFactory_Launcher.py
# или
python3 run_brand_factory.py
```
Двойной клик на Windows тоже работает. Скрипт сам поставит fastapi/uvicorn и откроет http://localhost:8002

## Вариант 2: Bash (Linux/Mac)
```bash
chmod +x run_brand_factory.sh
./run_brand_factory.sh
# или PORT=8003 ./run_brand_factory.sh
```

## Вариант 3: BAT (Windows)
Двойной клик по `run_brand_factory.bat`

## Что внутри после запуска
- UI: http://localhost:8002
- Вкладки: Phase1..Phase7, Overview, Factory Graph, Artifacts, Journey Map
- Слева проекты, справа агенты
- Phase1 — полностью реализован как пример: 7 агентов, 20 артефактов, Brand Manifest

## Проверка Phase1 за 1 минуту
1. Создай проект: + Новый проект → ниша "коучи", имя "Мария"
2. Phase1 → заполни слева ниша, эксперт, истории, proof, конкуренты → Сохранить
3. Нажми Run у market_researcher → Preview → Approve
4. Повтори для остальных 6 агентов по очереди
5. Открой Artifacts → 07_brand_manifest.md — главный документ
6. Artifacts на диске: brand_factory/projects/{id}/artifacts/

## Пример уже прогнан
`brand_factory/projects/demo_example/artifacts/` — 20 файлов, включая готовый манифест.

## Доки
- `brand_factory/docs/ANALYSIS_FULL.md` — полный анализ пути и что улучшено
- `brand_factory/README.md` — архитектура
- `BRAND_FACTORY_SUMMARY.md` — резюме

## HeyGen интеграция
Агент heygen_video_factory в Phase6 использует heygen_client.py из корня репо. Загрузи фото эксперта в Phase1 → оно уйдет как артефакт image в Phase6 → сгенерит видео.

## Для Arena/E2B preview
Сервер слушает 0.0.0.0:8002, поэтому доступен как https://8002-{sandbox}.e2b.app
