**User Request:** Write product content for Merino Wool Scarf, category: Accessories, material: merino wool, color: rust, audience: gift shoppers.

**Selected Workflow:** WF004 · Product Description Generator
**Routing:** keyword · confidence 0.859 · matched terms ['write', 'product', 'content'] (evidence 17.68, runner-up 3.3)
**Mode:** offline (deterministic rules and templates)
**Inputs:** product_file=data/sample/product_input.json; product_name=Merino Wool Scarf; category=Accessories; material=merino wool; color=rust; target_audience=gift shoppers

**Steps Executed:**
1. ✓ Validate required attributes — `collect_fields` → product_name, category, material, color, target_audience attributes present, attributes missing (0.8 ms)
2. ✓ create product description — `generate_content` → Meet the Merino Wool Scarf, part of our Accessories range, designed for gift shoppers. ... (0.3 ms)
3. ✓ generate short description — `generate_content` → Merino Wool Scarf in rust. (0.2 ms)
4. ✓ generate SEO title — `generate_content` → Merino Wool Scarf – rust | Accessories (0.3 ms)
5. ✓ generate meta description — `generate_content` → Shop the Merino Wool Scarf in rust for gift shoppers. Explore our accessories range. (0.2 ms)

**Status:** Completed

**Result:**

**SEO content: Merino Wool Scarf**

Generated a description, short description, SEO title and meta description from the supplied attributes only. Missing information (not invented, please supply before publishing): attributes.

*Content*

- **Product description:** Meet the Merino Wool Scarf, part of our Accessories range, designed for gift shoppers. Available in rust. Made from merino wool.
- **Short description:** Merino Wool Scarf in rust.
- **SEO title:** Merino Wool Scarf – rust \| Accessories
- **Meta description:** Shop the Merino Wool Scarf in rust for gift shoppers. Explore our accessories range.

*Missing information (explicitly not invented)*

- attributes

*Source attributes*

- **product_name:** Merino Wool Scarf
- **category:** Accessories
- **material:** merino wool
- **color:** rust
- **target_audience:** gift shoppers
- **attributes:** _not provided_
