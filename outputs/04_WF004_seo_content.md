**User Request:** Generate SEO content for this product.

**Selected Workflow:** WF004 · Product Description Generator
**Routing:** keyword · confidence 0.814 · matched terms ['generate', 'seo', 'content', 'product'] (evidence 18.37, runner-up 5.38)
**Mode:** offline (deterministic rules and templates)
**Inputs:** product_file=data/sample/product_input.json

**Steps Executed:**
1. ✓ Validate required attributes — `collect_fields` → product_name, category, attributes, color, target_audience attributes present, material missing (0.3 ms)
2. ✓ create product description — `generate_content` → Meet the Quilted Puffer Jacket, part of our Outerwear range, designed for urban commute... (0.1 ms)
3. ✓ generate short description — `generate_content` → Quilted Puffer Jacket in olive with water-resistant shell, zip-off hood and two zip poc... (0.1 ms)
4. ✓ generate SEO title — `generate_content` → Quilted Puffer Jacket – Olive | Outerwear (0.1 ms)
5. ✓ generate meta description — `generate_content` → Shop the Quilted Puffer Jacket in olive for urban commuters: water-resistant shell, zip... (0.1 ms)

**Status:** Completed

**Result:**

**SEO content: Quilted Puffer Jacket**

Generated a description, short description, SEO title and meta description from the supplied attributes only. Missing information (not invented, please supply before publishing): material.

*Content*

- **Product description:** Meet the Quilted Puffer Jacket, part of our Outerwear range, designed for urban commuters. Available in olive. Highlights: water-resistant shell, zip-off hood and two zip pockets.
- **Short description:** Quilted Puffer Jacket in olive with water-resistant shell, zip-off hood and two zip pockets.
- **SEO title:** Quilted Puffer Jacket – Olive \| Outerwear
- **Meta description:** Shop the Quilted Puffer Jacket in olive for urban commuters: water-resistant shell, zip-off hood and two zip pockets. Explore our outerwear range.

*Missing information (explicitly not invented)*

- material

*Source attributes*

- **product_name:** Quilted Puffer Jacket
- **category:** Outerwear
- **attributes:** water-resistant shell, zip-off hood, two zip pockets
- **material:** _not provided_
- **color:** Olive
- **target_audience:** Urban commuters
