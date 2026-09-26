import unittest
from src.merchant_os.taxonomy import MerchantTaxonomy, CustomerTaxonomy

class TestTaxonomy(unittest.TestCase):
    def test_merchant_category(self):
        x=MerchantTaxonomy().facets({"name":"متجر ملابس صنعاء","snippet":"فساتين وعبايات للبيع","city":"Sana'a"})
        self.assertEqual(x["primary_category"],"fashion")
        self.assertGreater(x["category_confidence"],0)

    def test_merchant_scale_needs_observed_sales(self):
        x=MerchantTaxonomy().facets({"name":"متجر إلكترونيات"})
        self.assertEqual(x["scale"]["band"],"unknown")

    def test_customer_age_is_not_inferred(self):
        x=CustomerTaxonomy().classify({"name":"Ahmed","age":30})
        self.assertFalse(x["age"]["verified"])
        self.assertEqual(x["age"]["band"],"unknown")

    def test_verified_customer_age(self):
        x=CustomerTaxonomy().classify({"age":32,"age_verified":True,"city":"Sana'a","category":"fashion"})
        self.assertEqual(x["age"]["band"],"25-34")
        self.assertEqual(x["purchase_categories"],["fashion"])

if __name__=="__main__":
    unittest.main()
