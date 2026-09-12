#!/usr/bin/env python3
"""Run only Aurora customization in isolated trees, not host/build setup."""
import re
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
# Verbatim upstream templates: eamonxg/luci-app-aurora-config
# commit 11a38cefaccb2b6ed71811164a16d67e68daa74e (all five built-in presets).
FIXTURES = {'amber-sand.template': "config aurora 'theme'\n"
                        "\toption light_bg '#faf9f5'\n"
                        "\toption light_surface '#faf9f5'\n"
                        "\toption light_text '#3d3929'\n"
                        "\toption light_brand '#c96442'\n"
                        "\toption light_on_brand '#fff'\n"
                        "\toption light_link '#c96442'\n"
                        "\toption light_info '#0e5794'\n"
                        "\toption light_warning '#653e00'\n"
                        "\toption light_success '#00523c'\n"
                        "\toption light_danger '#8d1925'\n"
                        "\toption light_text_muted '#7f7c70'\n"
                        "\toption light_text_subtle '#9a978c'\n"
                        "\toption light_surface_sunken '#f8f7f3'\n"
                        "\toption light_surface_overlay '#fffefa'\n"
                        "\toption light_hairline '#3d392921'\n"
                        "\toption light_hover_faint '#f0eeea'\n"
                        "\toption light_brand_hover '#b55230'\n"
                        "\toption light_brand_subtle '#f6e7df'\n"
                        "\toption light_brand_subtle_hover '#e9dad2'\n"
                        "\toption light_focus_ring '#c9644299'\n"
                        "\toption light_progress_start '#dd9880'\n"
                        "\toption light_progress_end '#c96442'\n"
                        "\toption light_info_surface '#d8f0ff'\n"
                        "\toption light_warning_surface '#ffecd2'\n"
                        "\toption light_success_surface '#d5f8e9'\n"
                        "\toption light_danger_surface '#ffe6e4'\n"
                        "\toption light_danger_surface_hover '#f9d9d7'\n"
                        "\toption light_control_bg '#fffefa'\n"
                        "\toption light_scrim '#0009'\n"
                        "\toption light_mega_menu_bg '#f7f6f0'\n"
                        "\toption light_mega_menu_scrim '#0d1c2a61'\n"
                        "\toption dark_bg '#262624'\n"
                        "\toption dark_surface '#30302e'\n"
                        "\toption dark_text '#c3c0b6'\n"
                        "\toption dark_brand '#d97757'\n"
                        "\toption dark_on_brand '#000'\n"
                        "\toption dark_link '#d97757'\n"
                        "\toption dark_info '#8dc1ff'\n"
                        "\toption dark_warning '#f0ba59'\n"
                        "\toption dark_success '#51bd85'\n"
                        "\toption dark_danger '#f17070'\n"
                        "\toption dark_text_muted '#83817a'\n"
                        "\toption dark_text_subtle '#63625d'\n"
                        "\toption dark_surface_sunken '#252523'\n"
                        "\toption dark_surface_overlay '#353533'\n"
                        "\toption dark_hairline '#c3c0b61a'\n"
                        "\toption dark_hover_faint '#c3c0b60d'\n"
                        "\toption dark_brand_hover '#c86848'\n"
                        "\toption dark_brand_subtle '#40332c'\n"
                        "\toption dark_brand_subtle_hover '#4b3d37'\n"
                        "\toption dark_focus_ring '#d9775799'\n"
                        "\toption dark_progress_start '#965a45'\n"
                        "\toption dark_progress_end '#d97757'\n"
                        "\toption dark_info_surface '#20344c'\n"
                        "\toption dark_warning_surface '#45310b'\n"
                        "\toption dark_success_surface '#153524'\n"
                        "\toption dark_danger_surface '#541f20'\n"
                        "\toption dark_danger_surface_hover '#602a2a'\n"
                        "\toption dark_control_bg '#252523'\n"
                        "\toption dark_scrim '#0009'\n"
                        "\toption dark_mega_menu_bg '#252523'\n"
                        "\toption dark_mega_menu_scrim '#00000080'\n"
                        '\toption struct_font_sans \'"Space Grotesk", "Lato", ui-sans-serif, '
                        "system-ui, sans-serif'\n"
                        '\toption struct_font_mono \'"Fira Code", ui-monospace, "SF Mono", Menlo, '
                        "Monaco, Consolas, monospace'\n"
                        "\toption struct_spacing '0.25rem'\n"
                        "\toption struct_content_width_centered '96rem'\n"
                        "\toption struct_radius_base '0.375rem'\n"
                        "\toption nav_type 'sidebar'\n"
                        "\toption toolbar_enabled '0'\n"
                        '\n'
                        'config toolbar_item\n'
                        "\toption title 'Overview'\n"
                        "\toption url '/cgi-bin/luci/admin/status/overview'\n"
                        "\toption icon 'overview.svg'\n"
                        "\toption enabled '1'\n"
                        '\n'
                        'config toolbar_item\n'
                        "\toption title 'System'\n"
                        "\toption url '/cgi-bin/luci/admin/system/system'\n"
                        "\toption icon 'system.svg'\n"
                        "\toption enabled '1'\n"
                        '\n'
                        'config toolbar_item\n'
                        "\toption title 'Software'\n"
                        "\toption url '/cgi-bin/luci/admin/system/package-manager'\n"
                        "\toption icon 'software.svg'\n"
                        "\toption enabled '0'\n"
                        '\n'
                        'config toolbar_item\n'
                        "\toption title 'Network'\n"
                        "\toption url '/cgi-bin/luci/admin/network/network'\n"
                        "\toption icon 'network.svg'\n"
                        "\toption enabled '1'\n",
 'default.template': "config aurora 'theme'\n"
                     "\toption light_bg '#f7fafc'\n"
                     "\toption light_surface '#fff'\n"
                     "\toption light_text '#121a22'\n"
                     "\toption light_brand '#0086bf'\n"
                     "\toption light_on_brand '#fff'\n"
                     "\toption light_link '#0086bf'\n"
                     "\toption light_info '#0e5794'\n"
                     "\toption light_warning '#653e00'\n"
                     "\toption light_success '#00523c'\n"
                     "\toption light_danger '#8d1925'\n"
                     "\toption light_text_muted '#5f666d'\n"
                     "\toption light_text_subtle '#7f858b'\n"
                     "\toption light_surface_sunken '#f4f7fa'\n"
                     "\toption light_surface_overlay '#fcffff'\n"
                     "\toption light_hairline '#121a2221'\n"
                     "\toption light_hover_faint '#ebeff2'\n"
                     "\toption light_brand_hover '#0074ac'\n"
                     "\toption light_brand_subtle '#dfecf5'\n"
                     "\toption light_brand_subtle_hover '#d1dfe8'\n"
                     "\toption light_focus_ring '#0186bf99'\n"
                     "\toption light_progress_start '#70aed5'\n"
                     "\toption light_progress_end '#0086bf'\n"
                     "\toption light_info_surface '#d8f0ff'\n"
                     "\toption light_warning_surface '#ffecd2'\n"
                     "\toption light_success_surface '#d5f8e9'\n"
                     "\toption light_danger_surface '#ffe6e4'\n"
                     "\toption light_danger_surface_hover '#f9d9d7'\n"
                     "\toption light_control_bg '#fcffff'\n"
                     "\toption light_scrim '#0009'\n"
                     "\toption light_mega_menu_bg '#f1f7fb'\n"
                     "\toption light_mega_menu_scrim '#0d1c2a61'\n"
                     "\toption dark_bg '#05070e'\n"
                     "\toption dark_surface '#141822'\n"
                     "\toption dark_text '#f9fafb'\n"
                     "\toption dark_brand '#00978f'\n"
                     "\toption dark_on_brand '#fff'\n"
                     "\toption dark_link '#00978f'\n"
                     "\toption dark_info '#8dc1ff'\n"
                     "\toption dark_warning '#f0ba59'\n"
                     "\toption dark_success '#51bd85'\n"
                     "\toption dark_danger '#f17070'\n"
                     "\toption dark_text_muted '#909297'\n"
                     "\toption dark_text_subtle '#5d6066'\n"
                     "\toption dark_surface_sunken '#0a0e17'\n"
                     "\toption dark_surface_overlay '#191d27'\n"
                     "\toption dark_hairline '#f9fafb1a'\n"
                     "\toption dark_hover_faint '#f9fafb0d'\n"
                     "\toption dark_brand_hover '#008880'\n"
                     "\toption dark_brand_subtle '#0a1a20'\n"
                     "\toption dark_brand_subtle_hover '#142329'\n"
                     "\toption dark_focus_ring '#00978f99'\n"
                     "\toption dark_progress_start '#166262'\n"
                     "\toption dark_progress_end '#00978f'\n"
                     "\toption dark_info_surface '#20344c'\n"
                     "\toption dark_warning_surface '#45310b'\n"
                     "\toption dark_success_surface '#153524'\n"
                     "\toption dark_danger_surface '#541f20'\n"
                     "\toption dark_danger_surface_hover '#602a2a'\n"
                     "\toption dark_control_bg '#0a0e17'\n"
                     "\toption dark_scrim '#0009'\n"
                     "\toption dark_mega_menu_bg '#0a0e17'\n"
                     "\toption dark_mega_menu_scrim '#00000080'\n"
                     '\toption struct_font_sans \'"Lato", ui-sans-serif, system-ui, sans-serif\'\n'
                     '\toption struct_font_mono \'ui-monospace, "SF Mono", Menlo, Monaco, '
                     "Consolas, monospace'\n"
                     "\toption struct_spacing '0.25rem'\n"
                     "\toption struct_content_width_centered '80rem'\n"
                     "\toption struct_radius_base '0.5rem'\n"
                     "\toption nav_type 'mega-menu'\n"
                     "\toption toolbar_enabled '1'\n"
                     "\toption icon_cache_version '0'\n"
                     "\toption logo_svg 'logo.svg'\n"
                     "\toption favicon_png ''\n"
                     "\toption favicon_ico 'favicon.ico'\n"
                     "\toption pwa_apple_touch 'apple-touch-icon.png'\n"
                     "\toption pwa_icon_192 'app-icon-192x192.png'\n"
                     "\toption pwa_icon_512 'app-icon-512x512.png'\n"
                     '\n'
                     'config toolbar_item\n'
                     "\toption title 'Overview'\n"
                     "\toption url '/cgi-bin/luci/admin/status/overview'\n"
                     "\toption icon 'overview.svg'\n"
                     "\toption enabled '1'\n"
                     '\n'
                     'config toolbar_item\n'
                     "\toption title 'System'\n"
                     "\toption url '/cgi-bin/luci/admin/system/system'\n"
                     "\toption icon 'system.svg'\n"
                     "\toption enabled '1'\n"
                     '\n'
                     'config toolbar_item\n'
                     "\toption title 'Software'\n"
                     "\toption url '/cgi-bin/luci/admin/system/package-manager'\n"
                     "\toption icon 'software.svg'\n"
                     "\toption enabled '0'\n"
                     '\n'
                     'config toolbar_item\n'
                     "\toption title 'Network'\n"
                     "\toption url '/cgi-bin/luci/admin/network/network'\n"
                     "\toption icon 'network.svg'\n"
                     "\toption enabled '1'\n",
 'monochrome.template': "config aurora 'theme'\n"
                        "\toption light_bg '#fcfcfc'\n"
                        "\toption light_surface '#fff'\n"
                        "\toption light_text '#000'\n"
                        "\toption light_brand '#000'\n"
                        "\toption light_on_brand '#fff'\n"
                        "\toption light_link '#000'\n"
                        "\toption light_info '#0e5794'\n"
                        "\toption light_warning '#653e00'\n"
                        "\toption light_success '#00523c'\n"
                        "\toption light_danger '#8d1925'\n"
                        "\toption light_text_muted '#414141'\n"
                        "\toption light_text_subtle '#676767'\n"
                        "\toption light_surface_sunken '#f7f7f7'\n"
                        "\toption light_surface_overlay '#fff'\n"
                        "\toption light_hairline '#00000021'\n"
                        "\toption light_hover_faint '#eee'\n"
                        "\toption light_brand_hover '#000'\n"
                        "\toption light_brand_subtle '#d5d5d5'\n"
                        "\toption light_brand_subtle_hover '#c8c8c8'\n"
                        "\toption light_focus_ring '#0009'\n"
                        "\toption light_progress_start '#383838'\n"
                        "\toption light_progress_end '#000'\n"
                        "\toption light_info_surface '#d8f0ff'\n"
                        "\toption light_warning_surface '#ffecd2'\n"
                        "\toption light_success_surface '#d5f8e9'\n"
                        "\toption light_danger_surface '#ffe6e4'\n"
                        "\toption light_danger_surface_hover '#f9d9d7'\n"
                        "\toption light_control_bg '#fff'\n"
                        "\toption light_scrim '#0009'\n"
                        "\toption light_mega_menu_bg '#f6f6f6'\n"
                        "\toption light_mega_menu_scrim '#0d1c2a61'\n"
                        "\toption dark_bg '#000'\n"
                        "\toption dark_surface '#090909'\n"
                        "\toption dark_text '#fff'\n"
                        "\toption dark_brand '#fff'\n"
                        "\toption dark_on_brand '#000'\n"
                        "\toption dark_link '#fff'\n"
                        "\toption dark_info '#8dc1ff'\n"
                        "\toption dark_warning '#f0ba59'\n"
                        "\toption dark_success '#51bd85'\n"
                        "\toption dark_danger '#f17070'\n"
                        "\toption dark_text_muted '#868686'\n"
                        "\toption dark_text_subtle '#4d4d4d'\n"
                        "\toption dark_surface_sunken '#030303'\n"
                        "\toption dark_surface_overlay '#0d0d0d'\n"
                        "\toption dark_hairline '#ffffff1a'\n"
                        "\toption dark_hover_faint '#ffffff0d'\n"
                        "\toption dark_brand_hover '#eee'\n"
                        "\toption dark_brand_subtle '#0d0d0d'\n"
                        "\toption dark_brand_subtle_hover '#161616'\n"
                        "\toption dark_focus_ring '#fff9'\n"
                        "\toption dark_progress_start '#999'\n"
                        "\toption dark_progress_end '#fff'\n"
                        "\toption dark_info_surface '#20344c'\n"
                        "\toption dark_warning_surface '#45310b'\n"
                        "\toption dark_success_surface '#153524'\n"
                        "\toption dark_danger_surface '#541f20'\n"
                        "\toption dark_danger_surface_hover '#602a2a'\n"
                        "\toption dark_control_bg '#030303'\n"
                        "\toption dark_scrim '#0009'\n"
                        "\toption dark_mega_menu_bg '#030303'\n"
                        "\toption dark_mega_menu_scrim '#00000080'\n"
                        '\toption struct_font_sans \'"Geist Sans", "Lato", ui-sans-serif, '
                        "system-ui, sans-serif'\n"
                        '\toption struct_font_mono \'"JetBrains Mono", ui-monospace, "SF Mono", '
                        "Menlo, Monaco, Consolas, monospace'\n"
                        "\toption struct_spacing '0.2rem'\n"
                        "\toption struct_content_width_centered '88rem'\n"
                        "\toption struct_radius_base '0rem'\n"
                        "\toption nav_type 'dropdown'\n"
                        "\toption toolbar_enabled '0'\n"
                        '\n'
                        'config toolbar_item\n'
                        "\toption title 'Overview'\n"
                        "\toption url '/cgi-bin/luci/admin/status/overview'\n"
                        "\toption icon 'overview.svg'\n"
                        "\toption enabled '1'\n"
                        '\n'
                        'config toolbar_item\n'
                        "\toption title 'System'\n"
                        "\toption url '/cgi-bin/luci/admin/system/system'\n"
                        "\toption icon 'system.svg'\n"
                        "\toption enabled '1'\n"
                        '\n'
                        'config toolbar_item\n'
                        "\toption title 'Software'\n"
                        "\toption url '/cgi-bin/luci/admin/system/package-manager'\n"
                        "\toption icon 'software.svg'\n"
                        "\toption enabled '0'\n"
                        '\n'
                        'config toolbar_item\n'
                        "\toption title 'Network'\n"
                        "\toption url '/cgi-bin/luci/admin/network/network'\n"
                        "\toption icon 'network.svg'\n"
                        "\toption enabled '1'\n",
 'sage-green.template': "config aurora 'theme'\n"
                        "\toption light_bg '#f8f7f4'\n"
                        "\toption light_surface '#fff'\n"
                        "\toption light_text '#1a1f2e'\n"
                        "\toption light_brand '#7c9082'\n"
                        "\toption light_on_brand '#fff'\n"
                        "\toption light_link '#7c9082'\n"
                        "\toption light_info '#0e5794'\n"
                        "\toption light_warning '#653e00'\n"
                        "\toption light_success '#00523c'\n"
                        "\toption light_danger '#8d1925'\n"
                        "\toption light_text_muted '#656973'\n"
                        "\toption light_text_subtle '#84878f'\n"
                        "\toption light_surface_sunken '#f8f7f3'\n"
                        "\toption light_surface_overlay '#fdfcf9'\n"
                        "\toption light_hairline '#1a1f2e21'\n"
                        "\toption light_hover_faint '#f0eeea'\n"
                        "\toption light_brand_hover '#6a7e70'\n"
                        "\toption light_brand_subtle '#e8eae6'\n"
                        "\toption light_brand_subtle_hover '#dbddd9'\n"
                        "\toption light_focus_ring '#7c908299'\n"
                        "\toption light_progress_start '#a6b3a8'\n"
                        "\toption light_progress_end '#7c9082'\n"
                        "\toption light_info_surface '#d8f0ff'\n"
                        "\toption light_warning_surface '#ffecd2'\n"
                        "\toption light_success_surface '#d5f8e9'\n"
                        "\toption light_danger_surface '#ffe6e4'\n"
                        "\toption light_danger_surface_hover '#f9d9d7'\n"
                        "\toption light_control_bg '#fdfcf9'\n"
                        "\toption light_scrim '#0009'\n"
                        "\toption light_mega_menu_bg '#f8f6f0'\n"
                        "\toption light_mega_menu_scrim '#0d1c2a61'\n"
                        "\toption dark_bg '#0a0a0a'\n"
                        "\toption dark_surface '#121212'\n"
                        "\toption dark_text '#f5f5f5'\n"
                        "\toption dark_brand '#7c9082'\n"
                        "\toption dark_on_brand '#000'\n"
                        "\toption dark_link '#7c9082'\n"
                        "\toption dark_info '#8dc1ff'\n"
                        "\toption dark_warning '#f0ba59'\n"
                        "\toption dark_success '#51bd85'\n"
                        "\toption dark_danger '#f17070'\n"
                        "\toption dark_text_muted '#919191'\n"
                        "\toption dark_text_subtle '#616161'\n"
                        "\toption dark_surface_sunken '#090909'\n"
                        "\toption dark_surface_overlay '#161616'\n"
                        "\toption dark_hairline '#f5f5f51a'\n"
                        "\toption dark_hover_faint '#f5f5f50d'\n"
                        "\toption dark_brand_hover '#6d8173'\n"
                        "\toption dark_brand_subtle '#1a1c1a'\n"
                        "\toption dark_brand_subtle_hover '#232524'\n"
                        "\toption dark_focus_ring '#7c908299'\n"
                        "\toption dark_progress_start '#4f5b53'\n"
                        "\toption dark_progress_end '#7c9082'\n"
                        "\toption dark_info_surface '#20344c'\n"
                        "\toption dark_warning_surface '#45310b'\n"
                        "\toption dark_success_surface '#153524'\n"
                        "\toption dark_danger_surface '#541f20'\n"
                        "\toption dark_danger_surface_hover '#602a2a'\n"
                        "\toption dark_control_bg '#090909'\n"
                        "\toption dark_scrim '#0009'\n"
                        "\toption dark_mega_menu_bg '#090909'\n"
                        "\toption dark_mega_menu_scrim '#00000080'\n"
                        '\toption struct_font_sans \'"Nunito", "Lato", ui-sans-serif, system-ui, '
                        "sans-serif'\n"
                        '\toption struct_font_mono \'"Maple Mono", ui-monospace, "SF Mono", Menlo, '
                        "Monaco, Consolas, monospace'\n"
                        "\toption struct_spacing '0.3rem'\n"
                        "\toption struct_content_width_centered '92rem'\n"
                        "\toption struct_radius_base '0.875rem'\n"
                        "\toption nav_type 'mega-menu'\n"
                        "\toption toolbar_enabled '1'\n"
                        '\n'
                        'config toolbar_item\n'
                        "\toption title 'Overview'\n"
                        "\toption url '/cgi-bin/luci/admin/status/overview'\n"
                        "\toption icon 'overview.svg'\n"
                        "\toption enabled '1'\n"
                        '\n'
                        'config toolbar_item\n'
                        "\toption title 'System'\n"
                        "\toption url '/cgi-bin/luci/admin/system/system'\n"
                        "\toption icon 'system.svg'\n"
                        "\toption enabled '1'\n"
                        '\n'
                        'config toolbar_item\n'
                        "\toption title 'Software'\n"
                        "\toption url '/cgi-bin/luci/admin/system/package-manager'\n"
                        "\toption icon 'software.svg'\n"
                        "\toption enabled '0'\n"
                        '\n'
                        'config toolbar_item\n'
                        "\toption title 'Network'\n"
                        "\toption url '/cgi-bin/luci/admin/network/network'\n"
                        "\toption icon 'network.svg'\n"
                        "\toption enabled '1'\n",
 'sky-blue.template': "config aurora 'theme'\n"
                      "\toption light_bg '#fff'\n"
                      "\toption light_surface '#f7f8f8'\n"
                      "\toption light_text '#0f1419'\n"
                      "\toption light_brand '#1e9df1'\n"
                      "\toption light_on_brand '#fff'\n"
                      "\toption light_link '#1e9df1'\n"
                      "\toption light_info '#0e5794'\n"
                      "\toption light_warning '#653e00'\n"
                      "\toption light_success '#00523c'\n"
                      "\toption light_danger '#8d1925'\n"
                      "\toption light_text_muted '#5f6367'\n"
                      "\toption light_text_subtle '#808487'\n"
                      "\toption light_surface_sunken '#f7f7f7'\n"
                      "\toption light_surface_overlay '#fff'\n"
                      "\toption light_hairline '#0f141921'\n"
                      "\toption light_hover_faint '#eee'\n"
                      "\toption light_brand_hover '#008add'\n"
                      "\toption light_brand_subtle '#e8f4ff'\n"
                      "\toption light_brand_subtle_hover '#dbe7f1'\n"
                      "\toption light_focus_ring '#1e9df199'\n"
                      "\toption light_progress_start '#7cbef5'\n"
                      "\toption light_progress_end '#1e9df1'\n"
                      "\toption light_info_surface '#d8f0ff'\n"
                      "\toption light_warning_surface '#ffecd2'\n"
                      "\toption light_success_surface '#d5f8e9'\n"
                      "\toption light_danger_surface '#ffe6e4'\n"
                      "\toption light_danger_surface_hover '#f9d9d7'\n"
                      "\toption light_control_bg '#fff'\n"
                      "\toption light_scrim '#0009'\n"
                      "\toption light_mega_menu_bg '#f6f6f6'\n"
                      "\toption light_mega_menu_scrim '#0d1c2a61'\n"
                      "\toption dark_bg '#000'\n"
                      "\toption dark_surface '#17181c'\n"
                      "\toption dark_text '#e7e9ea'\n"
                      "\toption dark_brand '#1c9cf0'\n"
                      "\toption dark_on_brand '#fff'\n"
                      "\toption dark_link '#1c9cf0'\n"
                      "\toption dark_info '#8dc1ff'\n"
                      "\toption dark_warning '#f0ba59'\n"
                      "\toption dark_success '#51bd85'\n"
                      "\toption dark_danger '#f17070'\n"
                      "\toption dark_text_muted '#797a7a'\n"
                      "\toption dark_text_subtle '#454646'\n"
                      "\toption dark_surface_sunken '#0d0e12'\n"
                      "\toption dark_surface_overlay '#1c1d21'\n"
                      "\toption dark_hairline '#e7e9ea1a'\n"
                      "\toption dark_hover_faint '#e7e9ea0d'\n"
                      "\toption dark_brand_hover '#008cdf'\n"
                      "\toption dark_brand_subtle '#00040c'\n"
                      "\toption dark_brand_subtle_hover '#030c15'\n"
                      "\toption dark_focus_ring '#1c9cf099'\n"
                      "\toption dark_progress_start '#21669a'\n"
                      "\toption dark_progress_end '#1c9cf0'\n"
                      "\toption dark_info_surface '#20344c'\n"
                      "\toption dark_warning_surface '#45310b'\n"
                      "\toption dark_success_surface '#153524'\n"
                      "\toption dark_danger_surface '#541f20'\n"
                      "\toption dark_danger_surface_hover '#602a2a'\n"
                      "\toption dark_control_bg '#0d0e12'\n"
                      "\toption dark_scrim '#0009'\n"
                      "\toption dark_mega_menu_bg '#0d0e12'\n"
                      "\toption dark_mega_menu_scrim '#00000080'\n"
                      '\toption struct_font_sans \'system-ui, -apple-system, "PingFang SC", '
                      '"Microsoft YaHei", sans-serif\'\n'
                      '\toption struct_font_mono \'ui-monospace, "SF Mono", Menlo, Monaco, '
                      "Consolas, monospace'\n"
                      "\toption struct_spacing '0.25rem'\n"
                      "\toption struct_content_width_centered '80rem'\n"
                      "\toption struct_radius_base '0.75rem'\n"
                      "\toption nav_type 'sidebar'\n"
                      "\toption toolbar_enabled '1'\n"
                      '\n'
                      'config toolbar_item\n'
                      "\toption title 'Overview'\n"
                      "\toption url '/cgi-bin/luci/admin/status/overview'\n"
                      "\toption icon 'overview.svg'\n"
                      "\toption enabled '1'\n"
                      '\n'
                      'config toolbar_item\n'
                      "\toption title 'System'\n"
                      "\toption url '/cgi-bin/luci/admin/system/system'\n"
                      "\toption icon 'system.svg'\n"
                      "\toption enabled '1'\n"
                      '\n'
                      'config toolbar_item\n'
                      "\toption title 'Software'\n"
                      "\toption url '/cgi-bin/luci/admin/system/package-manager'\n"
                      "\toption icon 'software.svg'\n"
                      "\toption enabled '0'\n"
                      '\n'
                      'config toolbar_item\n'
                      "\toption title 'Network'\n"
                      "\toption url '/cgi-bin/luci/admin/network/network'\n"
                      "\toption icon 'network.svg'\n"
                      "\toption enabled '1'\n"}


def fragment():
    script = (ROOT / 'user/default/custom.sh').read_text()
    return script[script.index('TPL_DIR='):script.index('# The temperature & fan')]


class AuroraCustomization(unittest.TestCase):
    def run_fragment(self, fixtures):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / 'package/luci-app-aurora-config/root/usr/share/aurora'
            if fixtures is not None:
                directory.mkdir(parents=True)
                for name, text in fixtures.items():
                    (directory / name).write_text(text)
            result = subprocess.run(['bash', '-e', '-c', fragment()], cwd=tmp,
                                    text=True, capture_output=True)
            return result, {p.name: p.read_text() for p in directory.glob('*.template')}

    def test_current_upstream_preserves_visible_output(self):
        result, actual = self.run_fragment(FIXTURES)
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = {name: re.sub(r"struct_radius_base '.*'", "struct_radius_base '0.125rem'",
                                re.sub(r"nav_type '.*'", "nav_type 'sidebar'", text))
                    for name, text in FIXTURES.items()}
        self.assertEqual(actual, expected)
        again, repeated = self.run_fragment(actual)
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(repeated, actual)

    def test_changed_template_content_aborts(self):
        for name in FIXTURES:
            for key in ('nav_type', 'struct_radius_base'):
                for change in ('rename', 'comment', 'double_quotes'):
                    with self.subTest(name=name, key=key, change=change):
                        fixtures = dict(FIXTURES)
                        if change == 'rename':
                            fixtures[name] = fixtures[name].replace(key, 'new_' + key)
                        elif change == 'comment':
                            fixtures[name] = fixtures[name].replace('option ' + key, '# option ' + key)
                        else:
                            fixtures[name] = re.sub(r"(option " + key + r") '([^']*)'",
                                                    r'\1 "\2"', fixtures[name])
                        result, _ = self.run_fragment(fixtures)
                        self.assertNotEqual(result.returncode, 0)
                        self.assertNotIn('theme-aurora nav preset applied!', result.stdout)

    def test_only_default_is_required(self):
        result, actual = self.run_fragment({'default.template': FIXTURES['default.template']})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(set(actual), {'default.template'})

    def test_trailing_whitespace_is_allowed(self):
        fixtures = {name: re.sub(r"(option (?:nav_type|struct_radius_base) '[^']*')",
                                 r'\1  \t', text) for name, text in FIXTURES.items()}
        result, _ = self.run_fragment(fixtures)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_required_templates_abort(self):
        for missing in (None, 'default.template'):
            with self.subTest(missing=missing):
                fixtures = None if missing is None else {
                    name: text for name, text in FIXTURES.items() if name != missing}
                result, _ = self.run_fragment(fixtures)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('theme-aurora nav preset applied!', result.stdout)


if __name__ == '__main__':
    unittest.main()
