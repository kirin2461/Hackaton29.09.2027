"""PDF-отчёт по технологическому присоединению.

Одна кнопка на фронте — и у проектировщика в руках документ:
параметры здания и трассы, смета, таблица «живучесть сети
до/после врезки» (энтропия, Фидлер, N-1, Монте-Карло) и карта
квартала с трассой. Собирается на лету из тех же данных, что
видит UI, — расхождений между экраном и отчётом нет.

Кириллица — через DejaVu Sans (идёт в комплекте matplotlib),
карта — matplotlib в PNG, вёрстка — fpdf2.
"""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")  # без X-сервера

import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MplPolygon

# DejaVu Sans с кириллицей идёт в комплекте matplotlib.
_FONT_DIR = Path(matplotlib.__file__).parent / "mpl-data" / "fonts" / "ttf"


def _render_map(layers: dict[str, list[dict]],
                building_polygon: list[list[float]],
                path: list[list[float]]) -> bytes:
    """PNG карты квартала: застройка, дороги, теплосеть, трасса."""
    fig, ax = plt.subplots(figsize=(8.2, 8.2), dpi=140)
    for f in layers.get("buildings", []):
        ax.add_patch(MplPolygon(f["coordinates"], closed=True,
                                facecolor="#d5d8dc", edgecolor="#aab0b6",
                                linewidth=0.4))
    for f in layers.get("roads", []):
        xs, ys = zip(*f["coordinates"])
        ax.plot(xs, ys, color="#7f8c8d", linewidth=0.9)
    for f in layers.get("heat_networks", []):
        xs, ys = zip(*f["coordinates"])
        ax.plot(xs, ys, color="#e74c3c", linewidth=2.2,
                label="Теплосеть" if f is layers["heat_networks"][0] else None)
    ax.add_patch(MplPolygon(building_polygon, closed=True,
                            facecolor="#2ecc71", edgecolor="#1e8449",
                            linewidth=1.2, label="Новое здание"))
    xs, ys = zip(*path)
    ax.plot(xs, ys, color="#00b4d8", linewidth=3.0,
            solid_capstyle="round", label="Трасса подключения")
    ax.plot(*path[0], marker="o", color="#e67e22", markersize=7)
    ax.plot(*path[-1], marker="s", color="#1e8449", markersize=7)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.legend(loc="upper right", framealpha=0.9, fontsize=9)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight",
                facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def build_report(building: dict[str, Any],
                 network_id: str,
                 path: list[list[float]],
                 variant: str,
                 estimate: dict[str, Any],
                 impact: dict[str, Any],
                 reliability: dict[str, Any],
                 layers: dict[str, list[dict]]) -> bytes:
    """Собирает PDF и возвращает его байты."""
    from fpdf import FPDF

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.add_page()
    pdf.add_font("DejaVu", "", str(_FONT_DIR / "DejaVuSans.ttf"))
    pdf.add_font("DejaVu", "B", str(_FONT_DIR / "DejaVuSans-Bold.ttf"))

    # --- заголовок ---
    pdf.set_font("DejaVu", "B", 16)
    pdf.multi_cell(0, 8,
                   "Отчёт по технологическому присоединению\nк тепловой сети")
    pdf.set_font("DejaVu", "", 10)
    pdf.set_text_color(90, 90, 90)
    pdf.set_x(pdf.l_margin)  # после multi_cell курсор уезжает вправо
    pdf.cell(0, 6,
             f"Сформировано сервисом «Теплосети 3D» · "
             f"{datetime.now():%d.%m.%Y %H:%M} · данные OpenStreetMap",
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_text_color(0, 0, 0)

    def section(title: str) -> None:
        pdf.set_font("DejaVu", "B", 12)
        pdf.set_fill_color(232, 240, 254)
        pdf.cell(0, 8, title, fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)
        pdf.set_font("DejaVu", "", 10)

    def row(label: str, value: str) -> None:
        pdf.cell(95, 6, label)
        pdf.set_font("DejaVu", "B", 10)
        pdf.cell(0, 6, value, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("DejaVu", "", 10)

    # --- здание ---
    section("Новое здание (точка Б)")
    row("Площадь застройки", f"{building['area_m2']} м²")
    row("Этажность", str(building["floors"]))
    row("Расчётная тепловая нагрузка", f"{building['heat_load_kw']} кВт")
    row("Теплосеть (точка А)", network_id)
    pdf.ln(2)

    # --- трасса и смета ---
    section(f"Трасса · вариант «{variant}»")
    row("Длина", f"{estimate['length_m']} м")
    row("Поворотов", str(estimate["turns"]))
    row("Переходов под дорогами", str(estimate["road_crossings"]))
    row("Теплопотери", f"{estimate['heat_loss_kw']} кВт")
    row("Стоимость строительства", f"{estimate['cost_mln_rub']} млн ₽")
    pdf.ln(2)

    # --- живучесть сети: таблица до/после ---
    section("Живучесть теплосети: до и после врезки")
    b, a = impact["before"], impact["after"]
    rel_b, rel_a = reliability["before"], reliability["after"]
    rows = [
        ("Равномерность сети (энтропия), 0..1",
         f"{b['entropy_norm']}", f"{a['entropy_norm']}"),
        ("Алгебраическая связность (Фидлер)",
         f"{b['fiedler']:.2e}", f"{a['fiedler']:.2e}"),
        ("N-1: худший отказ, % тепла без подачи",
         f"{rel_b['n1_worst_pct']}", f"{rel_a['n1_worst_pct']}"),
        ("N-1: средний отказ, %",
         f"{rel_b['n1_mean_pct']}", f"{rel_a['n1_mean_pct']}"),
        (f"Монте-Карло ({rel_b['mc_trials']} сценариев, "
         f"p={rel_b['fail_prob']}), %",
         f"{rel_b['mc_unserved_pct']}", f"{rel_a['mc_unserved_pct']}"),
    ]
    pdf.set_font("DejaVu", "B", 9)
    pdf.cell(100, 6, "Метрика", border=1)
    pdf.cell(45, 6, "До", border=1)
    pdf.cell(45, 6, "После", border=1, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("DejaVu", "", 9)
    for label, vb, va in rows:
        pdf.cell(100, 6, label, border=1)
        pdf.cell(45, 6, vb, border=1)
        pdf.cell(45, 6, va, border=1, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # --- карта ---
    section("Схема подключения")
    png = _render_map(layers, building["polygon"], path)
    pdf.image(io.BytesIO(png), x=15, w=180)

    return bytes(pdf.output())
