import csv
import argparse
from app import app, db, Product, ProductType, Brand

def to_float(value):
    value = str(value).strip().replace(",", ".")
    return float(value or 0)

def to_int(value, default=0):
    value = str(value).strip()
    return int(value) if value else default

def get_or_create_brand(name):
    brand = Brand.query.filter_by(name=name).first()
    if not brand:
        brand = Brand(name=name)
        db.session.add(brand)
        db.session.commit()
    return brand

def get_or_create_type_cmp():
    cmp_type = ProductType.query.filter_by(name="CMP").first()
    if not cmp_type:
        cmp_type = ProductType(name="CMP")
        db.session.add(cmp_type)
        db.session.commit()
    return cmp_type

def import_cmp(csv_path, update_existing=False):
    with app.app_context():
        cmp_type = get_or_create_type_cmp()
        added = 0
        updated = 0
        skipped = 0

        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter=";")

            for row in reader:
                classe = row["classe"].strip()
                nom_livre = row["nom_livre"].strip()
                code_barres = row["code_barres"].strip()
                prix_vente = to_float(row["prix_vente"])
                quantite = to_int(row.get("quantite", "0"), default=0)

                if not classe or not nom_livre or not code_barres:
                    skipped += 1
                    continue

                if len(code_barres) != 6 or not code_barres.isdigit():
                    print(f"Code-barres invalide ignoré : {code_barres}")
                    skipped += 1
                    continue

                brand = get_or_create_brand(classe)
                product_name = f"CMP - {classe} - {nom_livre}"

                existing = Product.query.filter_by(barcode=code_barres).first()

                if existing:
                    if update_existing:
                        existing.name = product_name
                        existing.brand_id = brand.id
                        existing.type_id = cmp_type.id
                        existing.purchase_price = 0
                        existing.sale_price = prix_vente
                        existing.quantity = quantite
                        existing.min_quantity = 5
                        updated += 1
                    else:
                        skipped += 1
                    continue

                product = Product(
                    name=product_name,
                    barcode=code_barres,
                    brand_id=brand.id,
                    type_id=cmp_type.id,
                    purchase_price=0,
                    sale_price=prix_vente,
                    quantity=quantite,
                    min_quantity=5
                )

                db.session.add(product)
                added += 1

        db.session.commit()

        print("Import CMP terminé.")
        print(f"Ajoutés : {added}")
        print(f"Modifiés : {updated}")
        print(f"Ignorés : {skipped}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Importer les livres scolaires CMP depuis un fichier CSV.")
    parser.add_argument("csv_path", help="Chemin du fichier CSV, exemple : cmp_data.csv")
    parser.add_argument("--update", action="store_true", help="Modifier les produits existants avec le même code-barres.")
    args = parser.parse_args()

    import_cmp(args.csv_path, update_existing=args.update)
