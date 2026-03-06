"""
HEM Product Catalogue v3 — Tab 1: Filter Products
===================================================
Lets users browse, search, and select products to add to the cart.

Layout:
  • Global search bar (searches ItemName, Fragrance, SKU Code)
  • Search mode  → shows matching products with all categories expanded
  • Filter mode  → Catalogue selectbox → Category multiselect
                   → per-category Subcategory multiselect
  • Action buttons: ADD SELECTED · ADD FILTERED · Clear Filters
  • Product list: thumbnail | name + badges | checkbox

NOTE: "Select All Categories" and "Deselect All" buttons are
      intentionally NOT present in this version.
"""
import pandas as pd
import streamlit as st

from config import NO_SELECTION_PLACEHOLDER
from database import load_products_db
from data_loader import create_safe_id
from cart import add_to_cart, add_selected_visible_to_cart, clear_filters_dropdown
from ui.components import product_thumbnail_html, stats_bar, empty_state


# ─────────────────────────────────────────────────────────────────────────────
def _render_product_list(df: pd.DataFrame, expanded: bool = False) -> None:
    """
    Render products grouped by Category inside collapsible expanders.

    Each row shows:
      [thumbnail] [product name + status badges] [checkbox]

    Args:
        df       – filtered product DataFrame to display
        expanded – whether to open all expanders by default (used in search mode)
    """
    if df.empty:
        empty_state("🔍", "No products match your current filters or search.")
        return

    # Collect ProductIDs already in cart for badge display
    cart_pids = {item.get("ProductID") for item in st.session_state.cart}

    # Load overridden ProductIDs for 'EDITED' badge
    db            = load_products_db()
    overridden_pids = set(db.get("product_overrides", {}).keys())

    # Group by Category (preserving original order)
    for category, cat_df in df.groupby("Category", sort=False):
        count = len(cat_df)

        with st.expander(f"**{category}**  ·  {count} products", expanded=expanded):

            # Bulk-add button for this category only
            _, btn_col = st.columns([5, 1])
            with btn_col:
                if st.button(
                    f"Add all {count}",
                    key=f"add_all_{create_safe_id(category)}",
                    use_container_width=True,
                ):
                    add_to_cart(cat_df)
                    st.rerun()

            # Iterate subcategories
            for subcat, sub_df in cat_df.groupby("Subcategory", sort=False):
                sub_str = str(subcat).strip()
                # Only show subcategory header if it has a real value
                if sub_str and sub_str.upper() != "N/A" and sub_str.lower() != "nan":
                    st.markdown(
                        f"<div class='subcat-header'>▸ {sub_str}"
                        f" <span style='font-size:10px;opacity:0.6;'>({len(sub_df)})</span></div>",
                        unsafe_allow_html=True,
                    )

                # Each product row
                for row_idx, row in sub_df.iterrows():
                    pid         = row["ProductID"]
                    cb_key      = f"checkbox_{pid}_{row_idx}"
                    in_cart     = pid in cart_pids
                    is_new      = row.get("IsNew") == 1
                    is_edited   = pid in overridden_pids
                    is_custom   = str(pid).startswith("CUST_")

                    # Build badge HTML
                    badges = ""
                    if is_new:
                        badges += "<span class='badge-new'>NEW</span>"
                    if is_edited:
                        badges += "<span class='badge-modified'>EDITED</span>"
                    if is_custom:
                        badges += "<span class='badge-custom'>CUSTOM</span>"
                    if in_cart:
                        badges += "<span class='badge-in-cart'>IN CART</span>"

                    # 3-column layout: thumb | name | checkbox
                    c_thumb, c_name, c_check = st.columns([0.45, 7, 1])

                    with c_thumb:
                        st.markdown(
                            product_thumbnail_html(row.get("ImageB64", ""), size=36),
                            unsafe_allow_html=True,
                        )
                    with c_name:
                        st.markdown(
                            f"**{row['ItemName']}** {badges}",
                            unsafe_allow_html=True,
                        )
                    with c_check:
                        st.checkbox(
                            "select",
                            value=in_cart,
                            key=cb_key,
                            label_visibility="hidden",
                        )


# ─────────────────────────────────────────────────────────────────────────────
def render_filter_tab(products_df: pd.DataFrame) -> None:
    """
    Render Tab 1 — Filter Products.
    Called from app.py inside `with tab1:`.
    """
    if products_df.empty:
        st.error("⚠️ No product data found. Check Excel file paths or run **Refresh** in the sidebar.")
        return

    working_df = products_df.copy()

    # ── Global search bar ─────────────────────────────────────────────────
    def _sync_search():
        st.session_state.item_search_query = st.session_state["_search_input_key"]

    search_term = st.text_input(
        "🔍 Global Search — products, fragrances, SKU codes",
        value=st.session_state.item_search_query,
        key="_search_input_key",
        on_change=_sync_search,
        placeholder="e.g. Rose, Lavender, HEM-001 …",
    ).strip().lower()

    # ═════════════════════════════════════════════════════════════════════
    # SEARCH MODE
    # ═════════════════════════════════════════════════════════════════════
    if search_term:
        working_df = products_df[
            products_df["ItemName"].str.lower().str.contains(search_term, na=False) |
            products_df["Fragrance"].str.lower().str.contains(search_term, na=False) |
            products_df["SKU Code"].str.lower().str.contains(search_term, na=False)
        ]
        stats_bar([
            ("Search results", f"{len(working_df)} products"),
            ("Cart", f"{len(st.session_state.cart)} items"),
        ])
        _render_product_list(working_df, expanded=True)
        return

    # ═════════════════════════════════════════════════════════════════════
    # FILTER MODE — Catalogue → Category → Subcategory
    # ═════════════════════════════════════════════════════════════════════
    col_filters, col_actions = st.columns([3, 1])

    with col_filters:
        # ── Catalogue selectbox ───────────────────────────────────────────
        catalogue_opts = [NO_SELECTION_PLACEHOLDER] + \
                         products_df["Catalogue"].unique().tolist()
        try:
            cat_idx = catalogue_opts.index(
                st.session_state.selected_catalogue_dropdown
            )
        except ValueError:
            cat_idx = 0

        selected_catalogue = st.selectbox(
            "📚 Catalogue",
            catalogue_opts,
            index=cat_idx,
            key="selected_catalogue_dropdown",
        )

        # ── Category multi-select (visible only after a catalogue is chosen) ──
        if selected_catalogue != NO_SELECTION_PLACEHOLDER:
            catalogue_df   = products_df[products_df["Catalogue"] == selected_catalogue]
            all_categories = catalogue_df["Category"].unique().tolist()

            # Sanitise session state in case catalogue changed
            valid_cats = [
                c for c in st.session_state.selected_categories_multi
                if c in all_categories
            ]
            if valid_cats != st.session_state.selected_categories_multi:
                st.session_state.selected_categories_multi = valid_cats

            selected_categories = st.multiselect(
                "🏷️ Category  (choose one or more)",
                all_categories,
                default=st.session_state.selected_categories_multi,
                key="category_multiselect",
            )
            st.session_state.selected_categories_multi = selected_categories

            # ── Per-category subcategory multi-select ─────────────────────
            filtered_parts: list[pd.DataFrame] = []

            if selected_categories:
                st.markdown(
                    '<div class="gold-divider" style="margin:10px 0 8px;"></div>',
                    unsafe_allow_html=True,
                )
                st.markdown(
                    '<span style="font-size:12px;color:#6b4040;'
                    'text-transform:uppercase;letter-spacing:1px;">'
                    '⬧ Sub-Category Filters</span>',
                    unsafe_allow_html=True,
                )

                for cat in selected_categories:
                    cat_data   = catalogue_df[catalogue_df["Category"] == cat]
                    raw_subs   = cat_data["Subcategory"].unique().tolist()
                    clean_subs = [
                        s for s in raw_subs
                        if str(s).strip()
                        and str(s).strip().upper() != "N/A"
                        and str(s).strip().lower() != "nan"
                    ]

                    if clean_subs:
                        chosen_subs = st.multiselect(
                            f"Sub-categories for **{cat}**",
                            clean_subs,
                            default=clean_subs,   # start with all selected
                            key=f"sub_{create_safe_id(cat)}",
                        )
                        # Keep all items with chosen subcategory OR no subcategory
                        mask = (
                            cat_data["Subcategory"].isin(chosen_subs) |
                            cat_data["Subcategory"].isin(["N/A", "nan", ""]) |
                            cat_data["Subcategory"].isna()
                        )
                        filtered_parts.append(cat_data[mask])
                    else:
                        filtered_parts.append(cat_data)

                working_df = (
                    pd.concat(filtered_parts, ignore_index=True)
                    if filtered_parts
                    else pd.DataFrame(columns=products_df.columns)
                )
            else:
                # No categories selected — show full catalogue
                working_df = catalogue_df

    # ── Action buttons ────────────────────────────────────────────────────
    with col_actions:
        st.markdown(
            '<div style="margin-top:28px;"></div>',
            unsafe_allow_html=True,
        )
        if st.button("✅ ADD SELECTED", use_container_width=True, type="primary"):
            add_selected_visible_to_cart(working_df)
            st.rerun()

        if st.button("➕ ADD FILTERED", use_container_width=True, type="secondary"):
            add_to_cart(working_df)
            st.rerun()

        st.button(
            "🗑 Clear Filters",
            use_container_width=True,
            on_click=clear_filters_dropdown,
        )

    st.markdown(
        '<div class="gold-divider" style="margin:14px 0 10px;"></div>',
        unsafe_allow_html=True,
    )

    # ── Product list ──────────────────────────────────────────────────────
    if selected_catalogue == NO_SELECTION_PLACEHOLDER:
        empty_state("📚", "Select a <strong>Catalogue</strong> above to begin browsing.")
    elif working_df.empty:
        empty_state("🏷️", "No products found for the selected filters.")
    else:
        stats_bar([
            ("Showing", f"{len(working_df)} products"),
            ("Categories", f"{working_df['Category'].nunique()}"),
            ("Cart", f"{len(st.session_state.cart)} items"),
        ])
        _render_product_list(working_df, expanded=False)
