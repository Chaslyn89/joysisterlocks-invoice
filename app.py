from flask import Flask, render_template, request, send_file
from weasyprint import HTML
from datetime import datetime
import io

app = Flask(__name__)

# Service menu based on real Kenyan pricing
SERVICES = {
    "retie": {"name": "Sister Locs Retie", "price": 3500},
    "micro_retie": {"name": "Micro Locs Retie", "price": 3500},
    "installation": {"name": "Sister Locs Full Installation", "price": 15000},
    "colour": {"name": "Sister Locs Colour & Styling", "price": 4500},
    "colour_retie": {"name": "Sister Locs Colour + Retie", "price": 5500},
    "wash_style": {"name": "Wash, Retie, Massage & Styling", "price": 3000},
}

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        # Get form data
        client_name = request.form.get("client_name")
        client_phone = request.form.get("client_phone")
        client_email = request.form.get("client_email")
        service = request.form.get("service")
        service_details = request.form.get("service_details", "")
        appointment_date = request.form.get("appointment_date")
        payment_method = request.form.get("payment_method")
        amount_paid = request.form.get("amount_paid")
        notes = request.form.get("notes", "")
        
        # Calculate total based on selected service
        service_info = SERVICES.get(service, {"name": service, "price": 0})
        total = int(service_info["price"])
        amount_paid_int = int(amount_paid) if amount_paid else 0
        balance = total - amount_paid_int
        
        # Generate invoice number
        invoice_number = f"JSL-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # Render HTML template with data
        html = render_template("invoice.html", 
            invoice_number=invoice_number,
            date=datetime.now().strftime("%Y-%m-%d"),
            client_name=client_name,
            client_phone=client_phone,
            client_email=client_email,
            service_name=service_info["name"],
            service_details=service_details,
            appointment_date=appointment_date,
            total=total,
            amount_paid=amount_paid_int,
            balance=balance,
            payment_method=payment_method,
            notes=notes,
            stylist_name="Joy"
        )
        
        # Generate PDF in memory (no folder needed)
        pdf_file = io.BytesIO()
        HTML(string=html).write_pdf(pdf_file)
        pdf_file.seek(0)
        
        # Return the PDF file for download
        return send_file(
            pdf_file, 
            as_attachment=True, 
            download_name=f"invoice_{invoice_number}.pdf",
            mimetype='application/pdf'
        )
    
    return render_template("form.html", services=SERVICES)

if __name__ == "__main__":
    app.run(debug=True)