import unittest

from app.services.catalog_service import CatalogService


class CatalogServiceTest(unittest.TestCase):
    def test_available_terms_starts_with_115_1_termid_72(self):
        terms = CatalogService.get_available_terms()

        self.assertEqual(terms[0], {"year": 115, "term": 1, "termid": 72, "label": "115 / 1"})

    def test_build_query_params_uses_official_field_names(self):
        params = CatalogService._build_query_params(
            termid=72,
            keyward="人工智慧",
            lang="E",
            stime="5",
            etime="7",
        )

        self.assertEqual(params["termid"], "72")
        self.assertEqual(params["keyward"], "人工智慧")
        self.assertEqual(params["lang"], "E")
        self.assertEqual(params["stime"], "5")
        self.assertEqual(params["etime"], "7")
        self.assertIn("teaName", params)
        self.assertIn("cName", params)


if __name__ == "__main__":
    unittest.main()
