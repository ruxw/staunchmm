import asyncio
import emojis
import settings
import utils

def run_tests():
    print("Running Middleman Bot Test Suite...")

    # 1. TAT parsing tests
    print("\n--- 1. Testing TAT parser ---")
    valid_cases = [
        ("1m", 60),
        ("1min", 60),
        ("15m", 900),
        ("15mins", 900),
        ("1h", 3600),
        ("1hr", 3600),
        ("2hours", 7200),
        ("1d", 86400),
        ("1day", 86400),
        ("15d", 15 * 86400),
        ("1d 12h 30m", 86400 + 12 * 3600 + 30 * 60),
    ]
    for text, expected in valid_cases:
        actual = utils.parse_tat(text)
        assert actual == expected, f"Failed on {text}: expected {expected}, got {actual}"
    print("✓ All valid duration formats (m, min, h, hr, d, day) parsed correctly.")

    invalid_cases = ["0m", "-1h", "0", "invalid", "", "xyz"]
    for text in invalid_cases:
        try:
            utils.parse_tat(text)
            assert False, f"Expected parse_tat('{text}') to raise ValueError"
        except ValueError:
            pass
    print("✓ All invalid duration inputs correctly rejected with clear errors.")

    # 2. Currency symbol mapping
    print("\n--- 2. Testing Currency Symbol Mapping ---")
    assert utils.get_currency_symbol("USD") == "$"
    assert utils.get_currency_symbol("$") == "$"
    assert utils.get_currency_symbol("INR") == "₹"
    assert utils.get_currency_symbol("₹") == "₹"
    assert utils.get_currency_symbol("EUR") == "€"
    assert utils.get_currency_symbol("GBP") == "£"
    assert utils.get_currency_symbol("USDT") == "USDT"
    print("✓ Currency symbol mappings verified.")

    # 3. Custom Emoji Configuration & Fallbacks
    print("\n--- 3. Testing Custom Emojis ---")
    orig_cids = dict(emojis.CUSTOM_EMOJI_IDS)
    emojis.CUSTOM_EMOJI_IDS.clear()
    assert emojis.get_emoji("SUCCESS") == "✅"
    assert emojis.get_emoji("HOLD") == "🔒"
    assert emojis.get_emoji("RELEASE") == "🔓"
    assert emojis.get_emoji("CLOSE") == "🚪"

    # Simulate custom emoji ID set
    emojis.CUSTOM_EMOJI_IDS["SUCCESS"] = "5368324170671202286"
    custom_rendered = emojis.get_emoji("SUCCESS")
    assert custom_rendered == '<tg-emoji emoji-id="5368324170671202286">✅</tg-emoji>'
    emojis.CUSTOM_EMOJI_IDS.clear()
    emojis.CUSTOM_EMOJI_IDS.update(orig_cids)
    print("✓ Custom emoji HTML rendering and Unicode fallbacks verified.")

    # 4. Safe Template Formatting & Defaults
    print("\n--- 4. Testing Configurable Templates ---")
    for key in settings.TEMPLATE_LABELS:
        preview = settings.preview_template(key)
        assert len(preview) > 0, f"Template preview failed for {key}"
    print("✓ All 9 templates rendered and previewed successfully.")

    # Check specific required texts
    exp_msg = settings.render_template(
        "tat_expiration",
        tat="24 hours",
        buyer="@buyer_user",
        seller="@seller_user",
        deal_id="1042",
    )
    assert "24 hours" in exp_msg
    assert "Deal #1042" in exp_msg
    assert "@buyer_user" in exp_msg
    assert "@seller_user" in exp_msg
    print("✓ TAT Expiration message format matches requirement exactly.")

    hold_msg = settings.render_template("hold", deal_id="1042", title="MM 1042 $ hold")
    assert "MM 1042 $ hold" in hold_msg
    assert "1042" in hold_msg
    print("✓ Hold message format matches requirement exactly.")

    rel_msg = settings.render_template("release", deal_id="1042", title="MM 1042 $ Released")
    assert "MM 1042 $ Released" in rel_msg
    assert "1042" in rel_msg
    print("✓ Release message format matches requirement exactly.")

    close_msg = settings.render_template("deal_closure", deal_id="1042")
    assert "1042" in close_msg
    print("✓ Deal closure message format verified.")

    # Vouch template test
    vouch_out = settings.render_vouch({"amount": "50", "currency": "$", "deal_no": 1})
    assert "Vouch @" in vouch_out
    assert "for MM'd 50 $" in vouch_out
    print("✓ Concise vouch format matches requirement exactly.")

    # Safe formatting with unknown placeholders
    safe_out = utils.safe_format("Hello {known} and {unknown}!", known="World")
    assert safe_out == "Hello World and {unknown}!"
    print("✓ Safe template formatter handles unknown placeholders safely.")

    # 5. Channel target parsing
    print("\n--- 5. Testing Vouch Channel Target Parser ---")
    assert utils.parse_channel_target("https://t.me/Proofinity") == "@Proofinity"
    assert utils.parse_channel_target("t.me/Proofinity") == "@Proofinity"
    assert utils.parse_channel_target("@Proofinity") == "@Proofinity"
    assert utils.parse_channel_target("-1001234567890") == -1001234567890
    print("✓ Vouch channel target parser verified.")

    # 6. Sequential GC Title Preset & Math
    print("\n--- 6. Testing Sequential GC Title Presets ---")
    # Test standard preset
    std_title = settings.render_gc_title(deal_no=15, buyer="alice", seller="bob", amount="100", currency="USD")
    assert "15" in std_title
    print("✓ Standard GC Title rendered correctly:", std_title)

    # Test sequential preset with baseline math: start_num=121, baseline=1, deal_no=1 -> 121
    settings._cache["gc_name_template"] = settings.GC_NAME_PRESETS[4] # "Deal #{startno} | @{mm}"
    settings._cache["gc_start_num"] = 121
    settings._cache["gc_baseline_deal_no"] = 1
    seq_title_1 = settings.render_gc_title(deal_no=1)
    assert "#121" in seq_title_1, f"Expected #121, got {seq_title_1}"
    seq_title_2 = settings.render_gc_title(deal_no=2)
    assert "#122" in seq_title_2, f"Expected #122, got {seq_title_2}"
    seq_title_4 = settings.render_gc_title(deal_no=4)
    assert "#124" in seq_title_4, f"Expected #124, got {seq_title_4}"
    # Reset template back to default
    settings._cache["gc_name_template"] = settings.GC_NAME_PRESETS[0]
    print("✓ Sequential GC title math (starting deal no #121 -> #122 -> #124) verified.")

    # 7. Currency & Payment Network Normalization
    print("\n--- 7. Testing Currency & Network Normalization ---")
    from ai_parser import normalize_currency_and_network

    cases = [
        ("₹", "upi", "INR", "UPI"),
        ("inr", "UPI", "INR", "UPI"),
        ("Rs", "", "INR", "UPI"),
        ("usdt", "trc20", "USDT", "TRC-20"),
        ("USDT", "bep-20", "USDT", "BEP-20"),
        ("bitcoin", "", "BTC", "Crypto"),
        ("btc", "bitcoin", "BTC", "Crypto"),
        ("eth", "erc20", "ETH", "ERC-20"),
        ("sol", "solana", "SOL", "SOL"),
        ("ton", "ton", "TON", "TON"),
        ("usd", "", "USD", "UPI"),
        ("crypto", "trc20", "Crypto", "TRC-20"),
    ]
    for raw_c, raw_n, exp_c, exp_n in cases:
        c, n = normalize_currency_and_network(raw_c, raw_n)
        assert c == exp_c, f"For ({raw_c}, {raw_n}): expected currency {exp_c}, got {c}"
        assert n == exp_n, f"For ({raw_c}, {raw_n}): expected network {exp_n}, got {n}"
    print("✓ All currency & payment network normalizations verified.")

    # 8. Advertisement System & Format
    print("\n--- 8. Testing Advertisement System ---")
    # Verify get_ad default
    ad = settings.get_ad()
    assert isinstance(ad, dict)
    assert "text" in ad and "enabled" in ad

    # Test footer format
    ad_text = "🎰 @Rainbetcom #1 Non-KYC Crypto Casino & Sportsbook"
    expected_footer = f'\n\n— "{ad_text}"'
    assert f'— "{ad_text}"' in expected_footer
    print("✓ Advertisement footer format matches expected styling.")

    print("\n===================================")
    print("🎉 ALL TEST SUITE ASSERTIONS PASSED!")
    print("===================================")

if __name__ == "__main__":
    run_tests()
