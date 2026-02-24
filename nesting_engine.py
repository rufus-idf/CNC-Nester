from rectpack import newPacker, PackingMode, MaxRectsBl, MaxRectsBssf, MaxRectsBaf


def solve_packer(
    panels,
    sheet_w,
    sheet_h,
    margin,
    kerf,
    rotate_flexible_panels=False,
    auto_rotate_all=False,
):
    """Run one packing strategy and return the best packer across algorithms."""
    usable_w = sheet_w - (margin * 2)
    usable_h = sheet_h - (margin * 2)

    algos = [MaxRectsBl, MaxRectsBssf, MaxRectsBaf]

    best_algo_packer = None
    best_algo_items = -1
    best_algo_sheets = float("inf")

    total_input_items = sum(p["Qty"] for p in panels)

    for algo in algos:
        packer = newPacker(
            mode=PackingMode.Offline,
            pack_algo=algo,
            rotation=auto_rotate_all,
        )

        for p in panels:
            for _ in range(p["Qty"]):
                p_w = p["Width"]
                p_l = p["Length"]
                grain = p["Grain?"]
                rid_label = f"{p['Label']}{'(G)' if grain else ''}"

                real_w = p_w + kerf
                real_l = p_l + kerf

                if grain:
                    packer.add_rect(real_w, real_l, rid=rid_label)
                else:
                    if rotate_flexible_panels:
                        packer.add_rect(real_l, real_w, rid=rid_label)
                    else:
                        packer.add_rect(real_w, real_l, rid=rid_label)

        safety_bins = max(300, total_input_items + 50)
        for _ in range(safety_bins):
            packer.add_bin(usable_w, usable_h)

        packer.pack()

        items_packed = len(packer.rect_list())
        sheets_used = len(packer)

        if items_packed > best_algo_items:
            best_algo_packer = packer
            best_algo_items = items_packed
            best_algo_sheets = sheets_used
        elif items_packed == best_algo_items and sheets_used < best_algo_sheets:
            best_algo_packer = packer
            best_algo_sheets = sheets_used

    return best_algo_packer


def run_smart_nesting(panels, sheet_w, sheet_h, margin, kerf):
    """
    Compare multiple strategies and return best result.

    Strategy A: Keep original orientation for all parts.
    Strategy B: Force-rotate all non-grain parts.
    Strategy C: If all parts are non-grain, allow rectpack to auto-rotate each part.
    """
    candidates = []

    packer_a = solve_packer(panels, sheet_w, sheet_h, margin, kerf, False, False)
    if packer_a:
        candidates.append(packer_a)

    packer_b = solve_packer(panels, sheet_w, sheet_h, margin, kerf, True, False)
    if packer_b:
        candidates.append(packer_b)

    # Mixed rotation is only safe when no part has locked grain.
    if all(not p.get("Grain?", False) for p in panels):
        packer_c = solve_packer(
            panels,
            sheet_w,
            sheet_h,
            margin,
            kerf,
            rotate_flexible_panels=False,
            auto_rotate_all=True,
        )
        if packer_c:
            candidates.append(packer_c)

    if not candidates:
        return None

    # Prefer maximum packed parts, then fewer sheets.
    return min(candidates, key=lambda p: (-len(p.rect_list()), len(p)))
