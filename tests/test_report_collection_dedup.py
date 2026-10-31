"""Ensure report-only duplicate accounting never hides verified multi-disc releases."""
import importlib.util
from pathlib import Path


spec = importlib.util.spec_from_file_location(
    "report_excel", Path(__file__).resolve().parents[1] / "server" / "report_excel.py"
)
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


def entry(name, game_id, state):
    row = [name, name + ".iso", "SLUS-12345", state, "NO", "reason",
           game_id, "", "", "", name, "", "standard", "COUNT"]
    return row


def test_noncompatible_duplicate_excluded_when_verified_release_present():
    pal = entry("007 PAL", "20816", "NO")
    ntsc = entry("007 USA", "20816", "YES")
    result = report.apply_collection_dedup([pal, ntsc])
    assert result[0][13].startswith("EXCLUDE")
    assert result[1][13] == "COUNT — verified"
    assert len([r for r in result if not r[13].startswith("EXCLUDE")]) == 1


def test_two_verified_discs_remain_counted():
    disc_one = entry("Devil May Cry 2 Disc 1", "7153", "YES")
    disc_two = entry("Devil May Cry 2 Disc 2", "7153", "YES")
    assert all(not r[13].startswith("EXCLUDE")
               for r in report.apply_collection_dedup([disc_one, disc_two]))


def test_unverified_pairs_and_unknown_ids_remain_counted():
    rows = [entry("PAL", "3062", "NO"), entry("USA", "3062", "NO"),
            entry("Game A", "", "UNKNOWN"), entry("Game B", "", "UNKNOWN")]
    assert all(not r[13].startswith("EXCLUDE")
               for r in report.apply_collection_dedup(rows))

def test_no_set_is_not_counted_as_ra_ready():
    data = {
        "status": "unmatched", "path": "PS2/Endgame.iso",
        "ra_game_title": "", "recommended_ra_title": "",
        "gamedb_title": "Endgame", "local_friendly_title": "Endgame",
        "preferred_patch_url": "", "local_serial": "SLES-12345",
        "ra_game_id": "", "recommended_ra_game_id": "",
        "preferred_release_name": "", "local_region": "Europe",
        "alternative_candidates": "", "disc_classification": "standard",
        "ra_set_status": "NO_SET", "no_set_ra_game_id": 123,
    }
    row = report.row_for(data)
    assert row[3] == "NO SET"
    assert row[14] == "NO_SET"


def test_no_set_rows_stay_in_effective_denominator():
    good = entry("Game US", "1234", "YES")
    no_set = entry("Endgame", "", "NO SET")
    rows = report.apply_collection_dedup([good, no_set])
    assert len([r for r in rows if not r[13].startswith("EXCLUDE")]) == 2


def test_patch_availability_does_not_imply_source_compatibility():
    data = {
        "status": "unmatched", "path": "PS2/SCES_524.60.Jak 3.iso",
        "local_serial": "SCES-52460", "local_region": "Europe",
        "gamedb_title": "Jak 3", "recommended_ra_title": "Jak 3 (USA)",
        "recommended_ra_game_id": "3065", "ra_game_id": "",
        "preferred_release_name": "Jak 3 (USA) (Debug Patch)",
        "preferred_region": "USA",
        "preferred_patch_url": "https://github.com/RetroAchievements/RAPatches/",
        "ra_set_status": "HAS_SET", "release_guidance": "",
        "alternative_candidates": "",
    }
    row = report.row_for(data)
    assert row[4] == "NO"
    assert row[18] == "AVAILABLE"
    assert "REGION MISMATCH" in row[20]
    assert "do not apply" in row[5]
    assert row[19].startswith("Debug")


def test_source_verified_changes_patch_to_ready_but_not_ra_compatible():
    data = {
        "status": "unmatched", "path": "PS2/SLUS_211.20.Psychonauts.iso",
        "local_serial": "SLUS-21120", "local_region": "USA",
        "gamedb_title": "Psychonauts", "recommended_ra_title": "Psychonauts (USA)",
        "recommended_ra_game_id": "3100", "ra_game_id": "",
        "preferred_release_name": "Psychonauts (USA) (Anti-Cheat)",
        "preferred_region": "USA", "preferred_patch_url": "https://github.com/RetroAchievements/RAPatches/",
        "ra_set_status": "HAS_SET", "release_guidance": "", "alternative_candidates": "",
    }
    source = "/mnt/retrodb-retronas/PS2/SLUS_211.20.Psychonauts.iso"
    row = report.row_for(data, {(source, data["recommended_ra_game_id"]): {"patch_url": data["preferred_patch_url"], "required_release": data["preferred_release_name"]}})
    assert (row[3], row[4], row[18], row[19]) == ("NO", "YES", "READY", "Anti-cheat")


def test_gt2_arcade_not_excluded_by_verified_simulation():
    arcade = entry("GT2 Arcade", "11278", "NO")
    arcade[2] = "SCUS-94455"
    simulation = entry("GT2 Simulation Rev 2", "11278", "YES")
    simulation[2] = "SCUS-94488"
    result = report.apply_collection_dedup([arcade, simulation])
    assert result[0][13] == "COUNT"
    assert result[1][13] == "COUNT — verified"


def test_different_serials_under_same_ra_id_not_deduplicated():
    first = entry("Driver 2 Disc 1", "11588", "YES")
    first[2] = "SLUS-01161"
    second = entry("Driver 2 Disc 2", "11588", "NO")
    second[2] = "SLUS-01318"
    assert report.apply_collection_dedup([first, second])[1][13] == "COUNT"


def test_region_difference_with_verified_alternative_is_not_action_required():
    pal = entry("European copy", "823", "NO")
    pal[2] = "SLES-01761"
    usa = entry("Verified USA copy", "823", "YES")
    usa[2] = "SLUS-00887"
    rows = report.apply_collection_dedup([pal, usa])
    assert rows[0][13] == "EXCLUDE — verified alternative on share"
    assert report.action_rows(rows, "Sony PlayStation") == []


def test_unverified_revision_without_a_replacement_is_not_urgent_action():
    row = entry("Old revision", "11588", "NO")
    assert report.action_rows([row], "Sony PlayStation") == []


def test_hash_error_still_requires_action():
    row = entry("Bad image", "11588", "ERROR")
    actions = report.action_rows([row], "Sony PlayStation")
    assert len(actions) == 1
    assert actions[0][5] == "Fix disc hash error"


def test_us_verified_pal_copy_soft_hidden_without_changing_hash_status():
    pal = entry("Harry Potter and the Philosopher's Stone", "11404", "NO")
    pal[2] = "SLES-03662"
    us = entry("Harry Potter and the Sorcerer's Stone", "11404", "YES")
    us[2] = "SLUS-01503"
    rows = report.apply_collection_dedup([pal, us])
    assert rows[0][3] == "NO"
    assert rows[0][13] == "EXCLUDE — verified alternative on share"
    assert "verified RA-compatible" in rows[0][5]
    assert rows[1][13] == "COUNT — verified"


def test_cross_region_multidisc_same_number_is_covered():
    pal = entry("Example Adventure (Disc 2)", "9001", "NO")
    pal[2] = "SLES-11111"
    us = entry("Example Adventure (Disc 2)", "9001", "YES")
    us[2] = "SLUS-22222"
    assert report.apply_collection_dedup([pal, us])[0][13].startswith("EXCLUDE")


def test_cross_region_different_disc_numbers_not_covered():
    pal = entry("Example Adventure (Disc 1)", "9001", "NO")
    pal[2] = "SLES-11111"
    us = entry("Example Adventure (Disc 2)", "9001", "YES")
    us[2] = "SLUS-22222"
    assert report.apply_collection_dedup([pal, us])[0][13] == "COUNT"


def test_unlabelled_copy_not_hidden_when_verified_set_has_multiple_discs():
    pal = entry("Example Adventure", "9001", "NO")
    pal[2] = "SLES-11111"
    us1 = entry("Example Adventure (Disc 1)", "9001", "YES")
    us1[2] = "SLUS-22221"
    us2 = entry("Example Adventure (Disc 2)", "9001", "YES")
    us2[2] = "SLUS-22222"
    assert report.apply_collection_dedup([pal, us1, us2])[0][13] == "COUNT"


def test_unknown_identity_not_soft_hidden():
    unknown = entry("Unrecognised release", "9001", "UNKNOWN")
    compatible = entry("Recognised release", "9001", "YES")
    assert report.apply_collection_dedup([unknown, compatible])[0][13] == "COUNT"


def test_kula_world_europe_identity_and_us_release_guidance():
    row = {
        "platform": "Sony PlayStation", "status": "unmatched",
        "path": "roms/sony/playstation1/iso/Kula World (Europe).cue",
        "local_serial": "SCES-01000", "local_region": "Europe",
        "gamedb_title": "PS One Kids Autumn 2000",
        "local_friendly_title": "Kula World (Europe)",
        "ra_game_id": "", "recommended_ra_game_id": "",
        "recommended_ra_title": "", "preferred_patch_url": "",
        "preferred_release_name": "", "preferred_region": "",
        "release_guidance": "", "alternative_candidates": "",
    }
    result = report.row_for(row)
    assert result[0] == "Kula World"
    assert str(result[6]) == "14865"
    assert result[7] == "Roll Away (USA) [SLUS-00724]"
    assert result[3] == "NO"
    assert "retroachievements.org/game/14865" in result[5]


def test_exhumed_europe_is_powerslave_no_set_with_optional_us_guidance():
    row = {
        "platform": "Sony PlayStation", "status": "unmatched",
        "path": "roms/sony/playstation1/iso/Exhumed [SLES-00097].cue",
        "local_serial": "SLES-00097", "local_region": "Europe",
        "gamedb_title": "Exhumed", "local_friendly_title": "Exhumed",
        "ra_set_status": "NO_SET", "no_set_ra_game_id": 15920,
        "ra_game_id": "", "recommended_ra_game_id": "",
        "recommended_ra_title": "", "preferred_patch_url": "",
        "preferred_release_name": "", "preferred_region": "",
        "release_guidance": "", "alternative_candidates": "",
    }
    result = report.row_for(row)
    assert result[0] == "Exhumed / PowerSlave"
    assert result[3] == "NO SET"
    assert str(result[6]) == "15920"
    assert "PowerSlave (USA)" in result[7]
    assert "NOT an RA-compatible upgrade" in result[5]
    assert "retroachievements.org/game/15920" in result[5]


def test_exhumed_stale_unknown_csv_not_action_required():
    raw = {
        "platform": "Sony PlayStation", "status": "unmatched",
        "path": "roms/sony/playstation1/iso/Exhumed [SLES-00097].cue",
        "local_serial": "SLES-00097", "local_region": "Europe",
        "gamedb_title": "Exhumed", "local_friendly_title": "Exhumed",
        "ra_set_status": "UNRESOLVED", "no_set_ra_game_id": "",
        "ra_game_id": "", "recommended_ra_game_id": "",
        "recommended_ra_title": "", "preferred_patch_url": "",
        "preferred_release_name": "", "preferred_region": "",
        "release_guidance": "", "alternative_candidates": "",
    }
    shown = report.row_for(raw)
    assert shown[3] == "NO SET"
    assert shown[14] == "NO_SET"
    assert str(shown[6]) == "15920"
    assert report.action_rows([shown], "Sony PlayStation") == []


def test_reviewed_ps1_crosswalks_survive_stale_unknown_export():
    for serial, name, game_id in (
        ("SLES-02017", "4x4 World Trophy", "18622"),
        ("SLES-04129", "Dance Europe", "19456"),
    ):
        raw = {
            "platform": "Sony PlayStation", "status": "unmatched",
            "path": "roms/sony/playstation1/iso/" + name + " [" + serial + "].cue",
            "local_serial": serial, "local_region": "Europe",
            "gamedb_title": name, "local_friendly_title": name,
            "ra_set_status": "UNRESOLVED", "no_set_ra_game_id": "",
            "ra_game_id": "", "recommended_ra_game_id": "",
            "recommended_ra_title": "", "preferred_patch_url": "",
            "preferred_release_name": "", "preferred_region": "",
            "release_guidance": "", "alternative_candidates": "",
        }
        shown = report.row_for(raw)
        assert shown[3] == "NO SET"
        assert shown[14] == "NO_SET"
        assert str(shown[6]) == game_id
        assert report.action_rows([shown], "Sony PlayStation") == []


def test_unlisted_aces_of_the_air_survives_stale_unknown_export():
    raw = {
        "platform": "Sony PlayStation", "status": "unmatched",
        "path": "roms/sony/playstation1/iso/Aces of the Air [SLUS-01470].cue",
        "local_serial": "SLUS-01470", "local_region": "USA",
        "gamedb_title": "Aces of the Air", "local_friendly_title": "Aces of the Air",
        "ra_set_status": "UNRESOLVED", "no_set_ra_game_id": "",
        "ra_game_id": "", "recommended_ra_game_id": "",
        "recommended_ra_title": "", "preferred_patch_url": "",
        "preferred_release_name": "", "preferred_region": "",
        "release_guidance": "", "alternative_candidates": "",
    }
    shown = report.row_for(raw)
    assert shown[3] == "NO SET"
    assert shown[14] == "NOT_LISTED"
    assert not shown[6]
    assert report.action_rows([shown], "Sony PlayStation") == []


def test_multidisc_display_name_preserves_disc_number_from_filename():
    base = {
        "platform": "Sony PlayStation", "status": "matched",
        "ra_game_title": "Fear Effect", "local_serial": "SLUS-00920",
        "preferred_patch_url": "", "preferred_release_name": "",
        "recommended_ra_title": "", "recommended_ra_game_id": "",
        "local_region": "USA", "preferred_region": "",
        "release_guidance": "", "alternative_candidates": "",
    }
    first = report.row_for({**base, "path": "iso/Fear Effect (Disc 1) [SLUS-00920].cue"})
    second = report.row_for({**base, "path": "iso/Fear Effect (Disc 2) [SLUS-01056].cue"})
    assert first[0] == "Fear Effect (Disc 1)"
    assert second[0] == "Fear Effect (Disc 2)"


def test_disc_number_is_not_repeated_when_catalogue_title_has_it():
    row = {
        "platform": "Sony PlayStation", "status": "matched",
        "ra_game_title": "Parasite Eve (Disc 1)",
        "path": "iso/Parasite Eve (Disc 1) [SLUS-00662].cue",
        "local_serial": "SLUS-00662", "preferred_patch_url": "",
        "preferred_release_name": "", "recommended_ra_title": "",
        "recommended_ra_game_id": "", "local_region": "USA",
        "preferred_region": "", "release_guidance": "",
        "alternative_candidates": "",
    }
    assert report.row_for(row)[0] == "Parasite Eve (Disc 1)"


def test_xcom_and_wipeout_reviewed_release_guidance():
    shared = {
        "platform": "Sony PlayStation", "status": "unmatched",
        "local_region": "Europe", "gamedb_title": "",
        "local_friendly_title": "", "ra_set_status": "UNRESOLVED",
        "recommended_ra_title": "", "recommended_ra_game_id": "",
        "ra_game_id": "", "preferred_release_name": "",
        "preferred_region": "", "preferred_patch_url": "",
        "alternative_candidates": "", "release_guidance": "",
    }
    xcom = report.row_for({**shared, "local_serial": "SLES-00054",
                           "path": "iso/X-Com Enemy Unknown [SLES-00054].cue"})
    assert xcom[3] == "NO" and str(xcom[6]) == "13493"
    assert "retroachievements.org/game/13493" in xcom[5]
    wipeout = report.row_for({**shared, "local_serial": "SLUS-00865",
                              "path": "iso/WipEout 3 [SLUS-00865].cue"})
    assert wipeout[3] == "NO" and str(wipeout[6]) == "13912"
    assert "Special Edition" in wipeout[7]
    assert "distinct edition" in wipeout[5]


def test_japanese_chrono_trigger_reviewed_ra_identity_in_stale_report():
    row = {
        "platform": "Sony PlayStation",
        "status": "unmatched",
        "path": "roms/sony/playstation1/iso/Chrono Trigger [SLPS-02430].cue",
        "local_serial": "SLPS-02430",
        "local_region": "Japan",
        "gamedb_title": "Chrono Trigger",
        "local_friendly_title": "Chrono Trigger",
        "ra_set_status": "UNRESOLVED",
        "ra_game_id": "",
        "recommended_ra_game_id": "",
        "recommended_ra_title": "",
        "preferred_patch_url": "",
        "preferred_release_name": "",
        "preferred_region": "",
        "release_guidance": "",
        "alternative_candidates": "",
    }
    result = report.row_for(row)
    assert result[0] == "Chrono Trigger"
    assert result[3] == "NO"
    assert str(result[6]) == "11243"
    assert "Chrono Trigger (USA) (Rev 1)" in result[7]
    assert "retroachievements.org/game/11243" in result[5]
    assert report.action_rows([result], "Sony PlayStation") == []

def test_capcom_snk_pal_crosswalk_in_unresolved_export():
    raw = {
        "platform": "Sony PlayStation", "status": "unmatched",
        "path": "roms/sony/playstation1/iso/Capcom vs. SNK Millennium Fight 2000 Pro [SLES-03889].cue",
        "local_serial": "SLES-03889", "local_region": "Europe",
        "gamedb_title": "Capcom vs. SNK: Millennium Fight 2000 Pro",
        "local_friendly_title": "", "ra_set_status": "UNRESOLVED",
        "ra_game_id": "", "recommended_ra_game_id": "",
        "recommended_ra_title": "", "preferred_patch_url": "",
        "preferred_release_name": "", "preferred_region": "",
        "release_guidance": "", "alternative_candidates": "",
    }
    row = report.row_for(raw)
    assert row[3] == "NO"
    assert str(row[6]) == "13918"
    assert row[7] == "Capcom vs. SNK Pro (USA)"
    assert row[14] == "HAS_SET"
    assert "retroachievements.org/game/13918" in row[5]
    assert report.action_rows([row], "Sony PlayStation") == []


def test_ace_combat_3_us_covered_only_by_two_verified_japanese_discs():
    us = entry("Ace Combat 3 Electrosphere", "11308", "NO")
    us[2] = "SLUS-00972"
    disc1 = entry("Ace Combat 3 Electrosphere (Disc 1)", "11308", "YES")
    disc1[2] = "SLPS-02020"
    disc2 = entry("Ace Combat 3 Electrosphere (Disc 2)", "11308", "YES")
    disc2[2] = "SLPS-02021"
    result = report.apply_collection_dedup([us, disc1, disc2])
    assert result[0][13] == "EXCLUDE — verified alternative on share"
    assert "already present" in result[0][5]
    assert all(r[13] == "COUNT — verified" for r in result[1:])


def test_ace_combat_3_us_not_covered_by_only_one_japanese_disc():
    us = entry("Ace Combat 3 Electrosphere", "11308", "NO")
    us[2] = "SLUS-00972"
    disc1 = entry("Ace Combat 3 Electrosphere (Disc 1)", "11308", "YES")
    disc1[2] = "SLPS-02020"
    result = report.apply_collection_dedup([us, disc1])
    assert result[0][13] == "COUNT"


def test_ace_combat_3_unverified_japanese_files_do_not_cover_us():
    us = entry("Ace Combat 3 Electrosphere", "11308", "NO")
    us[2] = "SLUS-00972"
    disc1 = entry("Ace Combat 3 Electrosphere (Disc 1)", "11308", "NO")
    disc1[2] = "SLPS-02020"
    disc2 = entry("Ace Combat 3 Electrosphere (Disc 2)", "11308", "NO")
    disc2[2] = "SLPS-02021"
    assert report.apply_collection_dedup([us, disc1, disc2])[0][13] == "COUNT"


def test_capcom_generations_multidisc_no_set_and_championship_bass_unlisted():
    base = {
        "platform": "Sony PlayStation", "status": "unmatched",
        "local_region": "Europe", "gamedb_title": "",
        "local_friendly_title": "", "ra_set_status": "UNRESOLVED",
        "ra_game_id": "", "recommended_ra_game_id": "",
        "recommended_ra_title": "", "no_set_ra_game_id": "",
        "preferred_patch_url": "", "preferred_release_name": "",
        "preferred_region": "", "release_guidance": "",
        "alternative_candidates": "",
    }
    for disc, serial, subtitle in (
        (2, "SLES-11881", "Chronicles of Arthur"),
        (3, "SLES-21881", "The First Generation"),
        (4, "SLES-31881", "Blazing Guns"),
    ):
        row = report.row_for({
            **base, "local_serial": serial,
            "path": f"iso/Capcom Generations (Disc {disc}) ({subtitle}) [{serial}].cue",
        })
        assert row[3] == "NO SET"
        assert row[14] == "NO_SET"
        assert str(row[6]) == "20367"
        assert f"Disc {disc}" in row[0]
        assert report.action_rows([row], "Sony PlayStation") == []

    bass = report.row_for({
        **base, "local_serial": "SLUS-01084", "local_region": "USA",
        "path": "iso/Championship Bass [SLUS-01084].cue",
        "gamedb_title": "Championship Bass",
    })
    assert bass[3] == "NO SET"
    assert bass[14] == "NOT_LISTED"
    assert not bass[6]
    assert report.action_rows([bass], "Sony PlayStation") == []


def test_motor_toon_grand_prix_2_pal_is_ra_8746_no_set():
    raw = {
        "platform": "Sony PlayStation", "status": "unmatched",
        "path": "roms/sony/playstation1/iso/Motor Toon Grand Prix 2 [SCES-00245].cue",
        "local_serial": "SCES-00245", "local_region": "Europe",
        "gamedb_title": "Motor Toon Grand Prix 2", "local_friendly_title": "",
        "ra_set_status": "UNRESOLVED", "ra_game_id": "",
        "recommended_ra_game_id": "", "recommended_ra_title": "",
        "no_set_ra_game_id": "", "preferred_patch_url": "",
        "preferred_release_name": "", "preferred_region": "",
        "release_guidance": "", "alternative_candidates": "",
    }
    row = report.row_for(raw)
    assert row[0] == "Motor Toon Grand Prix 2"
    assert row[3] == "NO SET"
    assert str(row[6]) == "8746"
    assert row[14] == "NO_SET"
    assert report.action_rows([row], "Sony PlayStation") == []


def test_max_power_racing_uk_is_c3_racing_with_active_ra_set():
    raw = {
        "platform": "Sony PlayStation", "status": "unmatched",
        "path": "roms/sony/playstation1/iso/Max Power Racing [SLES-01694].cue",
        "local_serial": "SLES-01694", "local_region": "Europe",
        "gamedb_title": "Max Power Racing", "local_friendly_title": "",
        "ra_set_status": "UNRESOLVED", "ra_game_id": "",
        "recommended_ra_game_id": "", "recommended_ra_title": "",
        "preferred_patch_url": "", "preferred_release_name": "",
        "preferred_region": "", "release_guidance": "",
        "alternative_candidates": "",
    }
    result = report.row_for(raw)
    assert result[0] == "Max Power Racing"
    assert result[3] == "NO"
    assert str(result[6]) == "17911"
    assert result[14] == "HAS_SET"
    assert "retroachievements.org/game/17911" in result[5]
    assert result[1] == "Max Power Racing [SLES-01694].cue"


def test_power_diggerz_pal_is_power_shovel_with_active_set():
    raw = {
        "platform": "Sony PlayStation", "status": "unmatched",
        "path": "iso/Power Diggerz [SLES-03388].cue",
        "local_serial": "SLES-03388", "local_region": "Europe",
        "gamedb_title": "Power Diggerz", "local_friendly_title": "",
        "ra_set_status": "UNRESOLVED", "ra_game_id": "",
        "recommended_ra_game_id": "", "recommended_ra_title": "",
        "preferred_patch_url": "", "preferred_release_name": "",
        "preferred_region": "", "release_guidance": "",
        "alternative_candidates": "",
    }
    row = report.row_for(raw)
    assert row[3] == "NO"
    assert str(row[6]) == "18046"
    assert row[14] == "HAS_SET"


def test_mike_tyson_boxing_unlisted_not_no_set():
    raw = {
        "platform": "Sony PlayStation", "status": "unmatched",
        "path": "iso/Mike Tyson Boxing [SLUS-01162].cue",
        "local_serial": "SLUS-01162", "local_region": "USA",
        "gamedb_title": "Mike Tyson Boxing", "local_friendly_title": "",
        "ra_set_status": "UNRESOLVED", "ra_game_id": "",
        "recommended_ra_game_id": "", "recommended_ra_title": "",
        "preferred_patch_url": "", "preferred_release_name": "",
        "preferred_region": "", "release_guidance": "",
        "alternative_candidates": "",
    }
    row = report.row_for(raw)
    assert row[3] == "NO SET"
    assert row[14] == "NOT_LISTED"
    assert not row[6]


def test_championship_motocross_sequel_does_not_inherit_predecessor_ra_id():
    raw = {
        "platform": "Sony PlayStation", "status": "unmatched",
        "path": "iso/Championship Motocross 2001 featuring Ricky Carmichael [SLUS-01230].cue",
        "local_serial": "SLUS-01230", "local_region": "USA",
        "gamedb_title": "Championship Motocross 2001 featuring Ricky Carmichael",
        "local_friendly_title": "", "ra_set_status": "UNRESOLVED",
        "ra_game_id": "", "recommended_ra_game_id": "",
        "recommended_ra_title": "", "preferred_patch_url": "",
        "preferred_release_name": "", "preferred_region": "",
        "release_guidance": "", "alternative_candidates": "",
    }
    row = report.row_for(raw)
    assert row[3] == "UNKNOWN"
    assert row[14] == "UNRESOLVED"
    assert str(row[6]) != "17195"
    assert "distinct" in row[5]


def test_phat_air_extreme_snowboarding_is_reviewed_unlisted():
    raw = {
        "platform": "Sony PlayStation", "status": "unmatched",
        "path": "iso/Phat Air Extreme Snowboarding [SLES-01178].cue",
        "local_serial": "SLES-01178", "local_region": "Europe",
        "gamedb_title": "Phat Air: Extreme Snowboarding",
        "local_friendly_title": "", "ra_set_status": "UNRESOLVED",
        "ra_game_id": "", "recommended_ra_game_id": "",
        "recommended_ra_title": "", "preferred_patch_url": "",
        "preferred_release_name": "", "preferred_region": "",
        "release_guidance": "", "alternative_candidates": "",
    }
    row = report.row_for(raw)
    assert row[3] == "NO SET"
    assert row[14] == "NOT_LISTED"
    assert not row[6]
    assert report.action_rows([row], "Sony PlayStation") == []


def test_monster_trucks_pal_is_thunder_truck_rally_no_set():
    raw = {
        "platform": "Sony PlayStation", "status": "unmatched",
        "path": "roms/sony/playstation1/iso/Monster Trucks [SLES-00314].cue",
        "local_serial": "SLES-00314", "local_region": "Europe",
        "gamedb_title": "Monster Trucks", "local_friendly_title": "",
        "ra_set_status": "UNRESOLVED", "ra_game_id": "",
        "recommended_ra_game_id": "", "recommended_ra_title": "",
        "no_set_ra_game_id": "", "preferred_patch_url": "",
        "preferred_release_name": "", "preferred_region": "",
        "release_guidance": "", "alternative_candidates": "Monster Racer [RA 29303; 0.741]",
    }
    row = report.row_for(raw)
    assert row[3] == "NO SET"
    assert row[14] == "NO_SET"
    assert str(row[6]) == "13442"
    assert row[0] == "Monster Trucks / Thunder Truck Rally"
    assert report.action_rows([row], "Sony PlayStation") == []


def test_pro_racer_pal_regional_alias_ra_17187():
    raw = {
        "platform": "Sony PlayStation", "status": "unmatched",
        "path": "iso/Pro Racer [SLES-03962].cue",
        "local_serial": "SLES-03962", "local_region": "Europe",
        "gamedb_title": "Pro Racer (Rev 1)", "local_friendly_title": "",
        "ra_set_status": "UNRESOLVED", "ra_game_id": "",
        "recommended_ra_game_id": "", "recommended_ra_title": "",
        "preferred_patch_url": "", "preferred_release_name": "",
        "preferred_region": "", "release_guidance": "",
        "alternative_candidates": "Moto Racer [RA 13959]",
    }
    row = report.row_for(raw)
    assert row[0] == "Pro Racer (Rev 1)"
    assert row[3] == "NO"
    assert str(row[6]) == "17187"
    assert row[14] == "HAS_SET"


def test_gt2_arcade_must_not_recommend_simulation_disc():
    raw = {
        "platform": "Sony PlayStation", "status": "unmatched",
        "path": "iso/Gran Turismo 2 (Arcade Mode) [SCUS-94455].cue",
        "local_serial": "SCUS-94455", "local_region": "USA",
        "gamedb_title": "Gran Turismo 2", "local_friendly_title": "",
        "ra_set_status": "HAS_SET", "ra_game_id": "",
        "recommended_ra_game_id": 11278,
        "recommended_ra_title": "Gran Turismo 2",
        "preferred_patch_url": "",
        "preferred_release_name": "Gran Turismo 2 (USA) (Simulation Mode) (Rev 2)",
        "preferred_region": "USA", "release_guidance": "",
        "alternative_candidates": "",
    }
    row = report.row_for(raw)
    assert row[0] == "Gran Turismo 2 (Arcade Mode)"
    assert "Arcade Mode" in row[7]
    assert "Simulation Mode" not in row[7]
    assert "different disc" in row[5]
