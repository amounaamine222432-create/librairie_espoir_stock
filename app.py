from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime, timedelta
from io import BytesIO
from html import escape
import random
import re
import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.styles import ParagraphStyle
import arabic_reshaper
from bidi.algorithm import get_display
from sqlalchemy import text

app = Flask(__name__)
app.config['SECRET_KEY'] = 'change-this-secret-key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///librairie_espoir.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)


class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)


class Brand(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    products = db.relationship('Product', backref='brand', lazy=True)


class ProductType(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    products = db.relationship('Product', backref='product_type', lazy=True)


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(180), nullable=False)
    barcode = db.Column(db.String(6), unique=True, nullable=False)
    brand_id = db.Column(db.Integer, db.ForeignKey('brand.id'), nullable=False)
    type_id = db.Column(db.Integer, db.ForeignKey('product_type.id'), nullable=False)
    purchase_price = db.Column(db.Float, nullable=False, default=0)
    sale_price = db.Column(db.Float, nullable=False, default=0)
    quantity = db.Column(db.Integer, nullable=False, default=0)
    min_quantity = db.Column(db.Integer, nullable=False, default=5)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    # product_id est optionnel :
    # - avec code-barres : on lie la vente au produit et on diminue le stock
    # - sans code-barres : vente manuelle, sans liaison avec le stock
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=True)

    manual_product_name = db.Column(db.String(180), nullable=True)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Float, nullable=False, default=0)
    total_price = db.Column(db.Float, nullable=False, default=0)
    sale_date = db.Column(db.DateTime, default=datetime.utcnow)

    product = db.relationship('Product', backref='sales')

    @property
    def product_name(self):
        if self.product:
            return self.product.name
        return self.manual_product_name or 'Produit manuel'

    @property
    def product_barcode(self):
        if self.product:
            return self.product.barcode
        return 'Manuel'


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_id'):
            flash('Veuillez vous connecter pour accéder à cette page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def generate_unique_barcode():
    while True:
        code = str(random.randint(100000, 999999))
        if not Product.query.filter_by(barcode=code).first():
            return code


def validate_barcode(code):
    return bool(re.fullmatch(r'\d{6}', code or ''))



def migrate_sale_table_if_needed():
    """
    Met à jour automatiquement l'ancienne table sale.
    Problème corrigé :
    - ancienne table sans manual_product_name
    - ancien product_id obligatoire, alors que la vente manuelle doit accepter product_id vide
    """
    rows = db.session.execute(text("PRAGMA table_info(sale)")).fetchall()

    # Si la table sale n'existe pas encore, db.create_all() va la créer.
    if not rows:
        return

    columns = {row[1]: row for row in rows}
    has_manual_name = 'manual_product_name' in columns
    product_id_is_not_null = bool(columns.get('product_id') and columns['product_id'][3] == 1)

    if has_manual_name and not product_id_is_not_null:
        return

    db.session.execute(text("PRAGMA foreign_keys=OFF"))
    db.session.execute(text("ALTER TABLE sale RENAME TO sale_old"))

    db.session.execute(text("""
        CREATE TABLE sale (
            id INTEGER NOT NULL,
            product_id INTEGER,
            manual_product_name VARCHAR(180),
            quantity INTEGER NOT NULL,
            unit_price FLOAT NOT NULL,
            total_price FLOAT NOT NULL,
            sale_date DATETIME,
            PRIMARY KEY (id),
            FOREIGN KEY(product_id) REFERENCES product (id)
        )
    """))

    old_columns = {row[1] for row in db.session.execute(text("PRAGMA table_info(sale_old)")).fetchall()}

    if 'manual_product_name' in old_columns:
        db.session.execute(text("""
            INSERT INTO sale (id, product_id, manual_product_name, quantity, unit_price, total_price, sale_date)
            SELECT id, product_id, manual_product_name, quantity, unit_price, total_price, sale_date
            FROM sale_old
        """))
    else:
        db.session.execute(text("""
            INSERT INTO sale (id, product_id, manual_product_name, quantity, unit_price, total_price, sale_date)
            SELECT id, product_id, NULL, quantity, unit_price, total_price, sale_date
            FROM sale_old
        """))

    db.session.execute(text("DROP TABLE sale_old"))
    db.session.execute(text("PRAGMA foreign_keys=ON"))
    db.session.commit()


def init_db():
    db.create_all()
    migrate_sale_table_if_needed()

    if not Admin.query.filter_by(username='admin').first():
        admin = Admin(username='admin', password_hash=generate_password_hash('admin123'))
        db.session.add(admin)

    default_brands = ['Oxford', 'Bic', 'Maped', 'Staedtler', 'Clairefontaine', 'L\'Espoir']
    for brand_name in default_brands:
        if not Brand.query.filter_by(name=brand_name).first():
            db.session.add(Brand(name=brand_name))

    default_types = ['Livre', 'Cahier', 'Stylo', 'Crayon', 'Fourniture scolaire', 'Papeterie', 'CMP']
    for type_name in default_types:
        if not ProductType.query.filter_by(name=type_name).first():
            db.session.add(ProductType(name=type_name))

    db.session.commit()

    if Product.query.count() == 0:
        brand_bic = Brand.query.filter_by(name='Bic').first()
        brand_oxford = Brand.query.filter_by(name='Oxford').first()
        type_stylo = ProductType.query.filter_by(name='Stylo').first()
        type_cahier = ProductType.query.filter_by(name='Cahier').first()
        samples = [
            Product(name='Stylo bleu classique', barcode='123456', brand_id=brand_bic.id, type_id=type_stylo.id, purchase_price=0.500, sale_price=0.800, quantity=120, min_quantity=20),
            Product(name='Cahier 96 pages', barcode='654321', brand_id=brand_oxford.id, type_id=type_cahier.id, purchase_price=1.200, sale_price=1.800, quantity=60, min_quantity=10),
        ]
        db.session.add_all(samples)
        db.session.commit()


@app.context_processor
def inject_now():
    return {'current_year': datetime.now().year}


@app.route('/')
def index():
    if session.get('admin_id'):
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        admin = Admin.query.filter_by(username=username).first()
        if admin and check_password_hash(admin.password_hash, password):
            session['admin_id'] = admin.id
            session['username'] = admin.username
            flash('Connexion réussie.', 'success')
            return redirect(url_for('dashboard'))
        flash('Nom d\'utilisateur ou mot de passe incorrect.', 'danger')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('Déconnexion réussie.', 'info')
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    total_products = Product.query.count()
    total_brands = Brand.query.count()
    total_types = ProductType.query.count()
    low_stock_products = Product.query.filter(Product.quantity <= Product.min_quantity).all()
    products = Product.query.all()
    stock_value = sum(p.quantity * p.purchase_price for p in products)
    sale_value = sum(p.quantity * p.sale_price for p in products)
    latest_products = Product.query.order_by(Product.created_at.desc()).limit(5).all()

    return render_template(
        'dashboard.html',
        total_products=total_products,
        total_brands=total_brands,
        total_types=total_types,
        low_stock_products=low_stock_products,
        stock_value=stock_value,
        sale_value=sale_value,
        latest_products=latest_products,
    )


@app.route('/products')
@login_required
def products():
    search = request.args.get('search', '').strip()
    type_id = request.args.get('type_id', '').strip()
    brand_id = request.args.get('brand_id', '').strip()

    query = Product.query
    if search:
        query = query.filter(
            db.or_(
                Product.name.ilike(f'%{search}%'),
                Product.barcode.ilike(f'%{search}%')
            )
        )
    if type_id:
        query = query.filter_by(type_id=int(type_id))
    if brand_id:
        query = query.filter_by(brand_id=int(brand_id))

    items = query.order_by(Product.created_at.desc()).all()
    brands = Brand.query.order_by(Brand.name.asc()).all()
    types = ProductType.query.order_by(ProductType.name.asc()).all()
    return render_template('products.html', products=items, brands=brands, types=types, search=search, selected_type=type_id, selected_brand=brand_id)


def get_filtered_products():
    search = request.args.get('search', '').strip()
    type_id = request.args.get('type_id', '').strip()
    brand_id = request.args.get('brand_id', '').strip()

    query = Product.query
    if search:
        query = query.filter(
            db.or_(
                Product.name.ilike(f'%{search}%'),
                Product.barcode.ilike(f'%{search}%')
            )
        )
    if type_id:
        query = query.filter_by(type_id=int(type_id))
    if brand_id:
        query = query.filter_by(brand_id=int(brand_id))

    return query.order_by(Product.created_at.desc()).all()


def register_pdf_fonts():
    """
    Police PDF compatible arabe + français.
    Sur Windows, Arial/Tahoma existent normalement.
    """
    font_candidates = [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/tahoma.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]

    bold_candidates = [
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/tahomabd.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]

    regular_font = next((path for path in font_candidates if os.path.exists(path)), None)
    bold_font = next((path for path in bold_candidates if os.path.exists(path)), regular_font)

    if regular_font:
        try:
            pdfmetrics.registerFont(TTFont("ArabicFont", regular_font))
        except Exception:
            pass

    if bold_font:
        try:
            pdfmetrics.registerFont(TTFont("ArabicFontBold", bold_font))
        except Exception:
            pass


def contains_arabic(text):
    text = str(text or "")
    return any("\u0600" <= char <= "\u06FF" for char in text)


def pdf_text(text):
    """
    Prépare le texte pour ReportLab :
    - français : affichage normal
    - arabe : reshape + bidi pour éviter les carrés et l'ordre inversé
    """
    text = str(text or "")

    if contains_arabic(text):
        text = arabic_reshaper.reshape(text)
        text = get_display(text)

    return text


def pdf_cell(text, style):
    return Paragraph(escape(pdf_text(text)), style)



@app.route('/products/pdf')
@login_required
def products_pdf():
    register_pdf_fonts()

    products = get_filtered_products()
    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=18,
        leftMargin=18,
        topMargin=22,
        bottomMargin=22,
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "TitleArabicFrench",
        parent=styles["Title"],
        fontName="ArabicFontBold",
        fontSize=16,
        leading=20,
        alignment=1,
    )

    normal_style = ParagraphStyle(
        "NormalArabicFrench",
        parent=styles["Normal"],
        fontName="ArabicFont",
        fontSize=9,
        leading=12,
    )

    header_style = ParagraphStyle(
        "HeaderArabicFrench",
        parent=styles["Normal"],
        fontName="ArabicFontBold",
        fontSize=8,
        leading=10,
        textColor=colors.white,
        alignment=1,
    )

    cell_style = ParagraphStyle(
        "CellArabicFrench",
        parent=styles["Normal"],
        fontName="ArabicFont",
        fontSize=7,
        leading=9,
    )

    elements = []

    title = Paragraph("Librairie L'Espoir - Liste des produits", title_style)
    date_line = Paragraph(f"Généré le : {datetime.now().strftime('%d/%m/%Y %H:%M')}", normal_style)
    count_line = Paragraph(f"Nombre de produits : {len(products)}", normal_style)

    elements.extend([title, Spacer(1, 8), date_line, count_line, Spacer(1, 14)])

    data = [[
        pdf_cell("Produit", header_style),
        pdf_cell("Code-barres", header_style),
        pdf_cell("Marque", header_style),
        pdf_cell("Type", header_style),
        pdf_cell("Achat", header_style),
        pdf_cell("Vente", header_style),
        pdf_cell("Qté", header_style),
        pdf_cell("Seuil", header_style),
        pdf_cell("État", header_style),
    ]]

    for product in products:
        state = "Stock faible" if product.quantity <= product.min_quantity else "Disponible"

        data.append([
            pdf_cell(product.name, cell_style),
            pdf_cell(product.barcode, cell_style),
            pdf_cell(product.brand.name if product.brand else "", cell_style),
            pdf_cell(product.product_type.name if product.product_type else "", cell_style),
            pdf_cell(f"{product.purchase_price:.3f} DT", cell_style),
            pdf_cell(f"{product.sale_price:.3f} DT", cell_style),
            pdf_cell(str(product.quantity), cell_style),
            pdf_cell(str(product.min_quantity), cell_style),
            pdf_cell(state, cell_style),
        ])

    if len(data) == 1:
        data.append([
            pdf_cell("Aucun produit", cell_style),
            pdf_cell("", cell_style),
            pdf_cell("", cell_style),
            pdf_cell("", cell_style),
            pdf_cell("", cell_style),
            pdf_cell("", cell_style),
            pdf_cell("", cell_style),
            pdf_cell("", cell_style),
            pdf_cell("", cell_style),
        ])

    table = Table(
        data,
        repeatRows=1,
        colWidths=[170, 75, 90, 105, 65, 65, 42, 42, 80]
    )

    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "ArabicFontBold"),
        ("FONTNAME", (0, 1), (-1, -1), "ArabicFont"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("FONTSIZE", (0, 1), (-1, -1), 7),
        ("ALIGN", (1, 1), (-1, -1), "CENTER"),
        ("ALIGN", (0, 1), (0, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD5E1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))

    elements.append(table)
    doc.build(elements)

    buffer.seek(0)
    filename = f"liste_produits_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"

    return send_file(
        buffer,
        as_attachment=True,
        download_name=filename,
        mimetype="application/pdf"
    )


@app.route('/products/add', methods=['GET', 'POST'])
@login_required
def add_product():
    brands = Brand.query.order_by(Brand.name.asc()).all()
    types = ProductType.query.order_by(ProductType.name.asc()).all()

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        barcode = request.form.get('barcode', '').strip() or generate_unique_barcode()
        brand_id = request.form.get('brand_id')
        type_id = request.form.get('type_id')
        purchase_price = float(request.form.get('purchase_price') or 0)
        sale_price = float(request.form.get('sale_price') or 0)
        quantity = int(request.form.get('quantity') or 0)
        min_quantity = int(request.form.get('min_quantity') or 5)

        if not name:
            flash('Le nom du produit est obligatoire.', 'danger')
            return render_template('product_form.html', product=None, brands=brands, types=types)
        if not validate_barcode(barcode):
            flash('Le code-barres doit contenir exactement 6 chiffres.', 'danger')
            return render_template('product_form.html', product=None, brands=brands, types=types)
        if Product.query.filter_by(barcode=barcode).first():
            flash('Ce code-barres existe déjà.', 'danger')
            return render_template('product_form.html', product=None, brands=brands, types=types)

        product = Product(
            name=name,
            barcode=barcode,
            brand_id=int(brand_id),
            type_id=int(type_id),
            purchase_price=purchase_price,
            sale_price=sale_price,
            quantity=quantity,
            min_quantity=min_quantity,
        )
        db.session.add(product)
        db.session.commit()
        flash('Produit ajouté avec succès.', 'success')
        return redirect(url_for('products'))

    return render_template('product_form.html', product=None, brands=brands, types=types, generated_barcode=generate_unique_barcode())


@app.route('/products/<int:product_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_product(product_id):
    product = Product.query.get_or_404(product_id)
    brands = Brand.query.order_by(Brand.name.asc()).all()
    types = ProductType.query.order_by(ProductType.name.asc()).all()

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        barcode = request.form.get('barcode', '').strip()
        brand_id = request.form.get('brand_id')
        type_id = request.form.get('type_id')
        purchase_price = float(request.form.get('purchase_price') or 0)
        sale_price = float(request.form.get('sale_price') or 0)
        quantity = int(request.form.get('quantity') or 0)
        min_quantity = int(request.form.get('min_quantity') or 5)

        if not name:
            flash('Le nom du produit est obligatoire.', 'danger')
            return render_template('product_form.html', product=product, brands=brands, types=types)
        if not validate_barcode(barcode):
            flash('Le code-barres doit contenir exactement 6 chiffres.', 'danger')
            return render_template('product_form.html', product=product, brands=brands, types=types)
        duplicated = Product.query.filter(Product.barcode == barcode, Product.id != product.id).first()
        if duplicated:
            flash('Ce code-barres existe déjà pour un autre produit.', 'danger')
            return render_template('product_form.html', product=product, brands=brands, types=types)

        product.name = name
        product.barcode = barcode
        product.brand_id = int(brand_id)
        product.type_id = int(type_id)
        product.purchase_price = purchase_price
        product.sale_price = sale_price
        product.quantity = quantity
        product.min_quantity = min_quantity
        db.session.commit()
        flash('Produit modifié avec succès.', 'success')
        return redirect(url_for('products'))

    return render_template('product_form.html', product=product, brands=brands, types=types)


@app.route('/products/<int:product_id>/delete', methods=['POST'])
@login_required
def delete_product(product_id):
    product = Product.query.get_or_404(product_id)
    db.session.delete(product)
    db.session.commit()
    flash('Produit supprimé.', 'info')
    return redirect(url_for('products'))


@app.route('/brands', methods=['GET', 'POST'])
@login_required
def brands():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('Le nom de la marque est obligatoire.', 'danger')
        elif Brand.query.filter_by(name=name).first():
            flash('Cette marque existe déjà.', 'warning')
        else:
            db.session.add(Brand(name=name))
            db.session.commit()
            flash('Marque ajoutée.', 'success')
        return redirect(url_for('brands'))

    items = Brand.query.order_by(Brand.name.asc()).all()
    return render_template('brands.html', brands=items)


@app.route('/brands/<int:brand_id>/delete', methods=['POST'])
@login_required
def delete_brand(brand_id):
    brand = Brand.query.get_or_404(brand_id)
    if Product.query.filter_by(brand_id=brand.id).first():
        flash('Impossible de supprimer une marque utilisée par des produits.', 'danger')
    else:
        db.session.delete(brand)
        db.session.commit()
        flash('Marque supprimée.', 'info')
    return redirect(url_for('brands'))


@app.route('/types', methods=['GET', 'POST'])
@login_required
def types():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('Le nom du type est obligatoire.', 'danger')
        elif ProductType.query.filter_by(name=name).first():
            flash('Ce type existe déjà.', 'warning')
        else:
            db.session.add(ProductType(name=name))
            db.session.commit()
            flash('Type ajouté.', 'success')
        return redirect(url_for('types'))

    items = ProductType.query.order_by(ProductType.name.asc()).all()
    return render_template('types.html', types=items)


@app.route('/types/<int:type_id>/delete', methods=['POST'])
@login_required
def delete_type(type_id):
    product_type = ProductType.query.get_or_404(type_id)
    if Product.query.filter_by(type_id=product_type.id).first():
        flash('Impossible de supprimer un type utilisé par des produits.', 'danger')
    else:
        db.session.delete(product_type)
        db.session.commit()
        flash('Type supprimé.', 'info')
    return redirect(url_for('types'))

@app.route('/sales', methods=['GET', 'POST'])
@login_required
def sales():
    if request.method == 'POST':
        barcode = request.form.get('barcode', '').strip()
        manual_product_name = request.form.get('manual_product_name', '').strip()
        quantity = int(request.form.get('quantity') or 0)
        manual_unit_price = float(request.form.get('manual_unit_price') or 0)

        if quantity <= 0:
            flash('La quantité vendue doit être supérieure à 0.', 'danger')
            return redirect(url_for('sales'))

        # CAS 1 : Vente par code-barres
        if barcode:
            if not validate_barcode(barcode):
                flash('Le code-barres doit contenir exactement 6 chiffres.', 'danger')
                return redirect(url_for('sales'))

            product = Product.query.filter_by(barcode=barcode).first()

            if not product:
                flash('Aucun produit trouvé avec ce code-barres. Vous pouvez l’ajouter comme vente manuelle.', 'danger')
                return redirect(url_for('sales'))

            if quantity > product.quantity:
                flash('Stock insuffisant pour ce produit.', 'danger')
                return redirect(url_for('sales'))

            unit_price = product.sale_price
            total_price = quantity * unit_price

            sale = Sale(
                product_id=product.id,
                manual_product_name=None,
                quantity=quantity,
                unit_price=unit_price,
                total_price=total_price
            )

            # Diminution automatique du stock seulement si le produit existe par code-barres
            product.quantity -= quantity

            db.session.add(sale)
            db.session.commit()

            flash('Vente par code-barres ajoutée. Le stock a été diminué automatiquement.', 'success')
            return redirect(url_for('sales'))

        # CAS 2 : Vente manuelle sans code-barres
        if not manual_product_name:
            flash('Si vous ne saisissez pas de code-barres, le nom du produit est obligatoire.', 'danger')
            return redirect(url_for('sales'))

        if manual_unit_price <= 0:
            flash('Le prix de vente manuel doit être supérieur à 0.', 'danger')
            return redirect(url_for('sales'))

        total_price = quantity * manual_unit_price

        sale = Sale(
            product_id=None,
            manual_product_name=manual_product_name,
            quantity=quantity,
            unit_price=manual_unit_price,
            total_price=total_price
        )

        # Vente manuelle : pas de diminution du stock, car le produit n’est pas lié au catalogue
        db.session.add(sale)
        db.session.commit()

        flash('Vente manuelle ajoutée. Aucun stock n’a été diminué.', 'success')
        return redirect(url_for('sales'))

    selected_date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))

    try:
        start_date = datetime.strptime(selected_date, '%Y-%m-%d')
    except ValueError:
        start_date = datetime.now()
        selected_date = start_date.strftime('%Y-%m-%d')

    end_date = start_date + timedelta(days=1)

    day_sales = Sale.query.filter(
        Sale.sale_date >= start_date,
        Sale.sale_date < end_date
    ).order_by(Sale.sale_date.desc()).all()

    total_day = sum(sale.total_price for sale in day_sales)
    total_quantity = sum(sale.quantity for sale in day_sales)

    return render_template(
        'sales.html',
        day_sales=day_sales,
        selected_date=selected_date,
        total_day=total_day,
        total_quantity=total_quantity
    )


@app.route('/sales/<int:sale_id>/delete', methods=['POST'])
@login_required
def delete_sale(sale_id):
    sale = Sale.query.get_or_404(sale_id)

    # Si la vente est liée à un produit du stock, on restaure le stock.
    # Si c’est une vente manuelle, il n’y a rien à restaurer.
    if sale.product:
        sale.product.quantity += sale.quantity

    db.session.delete(sale)
    db.session.commit()

    flash('Vente supprimée. Le stock a été restauré seulement si la vente était liée à un produit.', 'info')
    return redirect(url_for('sales'))



@app.route('/cmp/add', methods=['GET', 'POST'])
@login_required
def add_cmp_product():
    """
    Ajout rapide des livres scolaires CMP :
    - Type = CMP
    - Marque = classe
    - Nom = CMP - classe - nom du livre
    - Code-barres = 6 chiffres
    - Achat = 0
    - Vente = prix
    - Quantité = saisie manuelle
    - Seuil = 5
    """
    if request.method == 'POST':
        classe = request.form.get('classe', '').strip()
        book_name = request.form.get('book_name', '').strip()
        barcode = request.form.get('barcode', '').strip()
        sale_price = float(request.form.get('sale_price') or 0)
        quantity = int(request.form.get('quantity') or 0)

        if not classe:
            flash('La classe est obligatoire.', 'danger')
            return redirect(url_for('add_cmp_product'))

        if not book_name:
            flash('Le nom du livre est obligatoire.', 'danger')
            return redirect(url_for('add_cmp_product'))

        if not validate_barcode(barcode):
            flash('Le code-barres doit contenir exactement 6 chiffres.', 'danger')
            return redirect(url_for('add_cmp_product'))

        if Product.query.filter_by(barcode=barcode).first():
            flash('Ce code-barres existe déjà.', 'danger')
            return redirect(url_for('add_cmp_product'))

        if sale_price < 0:
            flash('Le prix de vente ne peut pas être négatif.', 'danger')
            return redirect(url_for('add_cmp_product'))

        if quantity < 0:
            flash('La quantité ne peut pas être négative.', 'danger')
            return redirect(url_for('add_cmp_product'))

        cmp_type = ProductType.query.filter_by(name='CMP').first()
        if not cmp_type:
            cmp_type = ProductType(name='CMP')
            db.session.add(cmp_type)
            db.session.commit()

        # La marque correspond à la classe
        brand = Brand.query.filter_by(name=classe).first()
        if not brand:
            brand = Brand(name=classe)
            db.session.add(brand)
            db.session.commit()

        product_name = f"CMP - {classe} - {book_name}"

        product = Product(
            name=product_name,
            barcode=barcode,
            brand_id=brand.id,
            type_id=cmp_type.id,
            purchase_price=0,
            sale_price=sale_price,
            quantity=quantity,
            min_quantity=5
        )

        db.session.add(product)
        db.session.commit()

        flash('Livre CMP ajouté avec succès.', 'success')
        return redirect(url_for('products'))

    return render_template('cmp_form.html')


@app.route('/cmp')
@login_required
def cmp_products():
    cmp_type = ProductType.query.filter_by(name='CMP').first()

    if not cmp_type:
        items = []
    else:
        items = Product.query.filter_by(type_id=cmp_type.id).order_by(Product.created_at.desc()).all()

    return render_template('cmp_products.html', products=items)


if __name__ == '__main__':
    with app.app_context():
        init_db()
    app.run(debug=True)
