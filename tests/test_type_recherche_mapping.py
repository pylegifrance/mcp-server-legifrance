from server import _normalize_type_recherche


def test_maps_legacy_expression_exacte_to_exacte():
    assert _normalize_type_recherche("EXPRESSION_EXACTE") == "EXACTE"


def test_maps_legacy_au_moins_un_mot_to_un_des_mots():
    assert _normalize_type_recherche("AU_MOINS_UN_MOT") == "UN_DES_MOTS"


def test_passes_through_already_canonical_values():
    assert _normalize_type_recherche("TOUS_LES_MOTS_DANS_UN_CHAMP") == "TOUS_LES_MOTS_DANS_UN_CHAMP"


def test_passes_through_none():
    assert _normalize_type_recherche(None) is None
