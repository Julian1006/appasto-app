img = {
    39: "images/pollo/Pechuga entera.webp",
    40: "images/pollo/Filete de pechuga.webp",
    41: "images/pollo/Pierna pernil.webp",
    42: "images/pollo/Churrasco de pollo.webp",
    43: "images/pollo/Muslo.webp",
    44: "images/pollo/Contra muslo.webp",
    45: "images/pollo/Ala.webp",
    46: "images/pollo/Colombina de ala.webp",
    47: "images/pollo/Corazones de pollo.webp",
    48: "images/pollo/Mollejas de pollo.webp",
    57: "images/pollo/Higado de pollo.webp",
    58: "images/pollo/Menudencias.webp",
    49: "images/pescado/Filete de salmon.webp",
    50: "images/pescado/Filete de atun.webp",
    51: "images/pescado/Camaron precocido.webp",
    59: "images/pescado/Camaron Crudo.webp",
    52: "images/pescado/Bagre dorado.webp",
    53: "images/pescado/Trucha deshuesada.webp",
    54: "images/pescado/Mojarra.webp",
    55: "images/pescado/Filete de tilapia.webp",
    56: "images/pescado/Bandeja de basa.webp",
    60: "images/Charcuteria premium/Chorizo fazenda.webp",
    61: "images/Charcuteria premium/Chorizo fazenda coctel.webp",
    62: "images/Charcuteria premium/Chorizo fazenda mixto.webp",
    63: "images/Charcuteria premium/Morcilla casera fazenda.webp",
    64: "images/Charcuteria premium/Morcilla coctel fazenda.webp",
    65: "images/Charcuteria premium/Costillitas ahumadas fazenda.webp",
    66: "images/Charcuteria premium/Salchichon fazenda.webp",
    67: "images/Charcuteria premium/Tocineta ahumada.webp",
    68: "images/Charcuteria premium/Chorizo argentino el dia que me quieras.webp",
    69: "images/Charcuteria premium/Chorizo Antioqueno el dia que me quieras.webp",
    70: "images/Charcuteria premium/Chorizo Espanol el dia que me quieras.webp",
    71: "images/Charcuteria premium/Morcilla antioquena el dia que me quieras.webp",
    72: "images/Charcuteria premium/Morcilla Burgos el dia que me quieras.webp",
    73: "images/Lacteos y huevos/Huevo gentil AA x 30 und.webp",
    74: "images/Lacteos y huevos/Huevo gentil AA x 12 und.webp",
    75: "images/Lacteos y huevos/Huevo AAA x 30 und.webp",
    76: "images/Lacteos y huevos/Huevo AA x 30 und.webp",
    77: "images/Lacteos y huevos/Queso Costeno.webp",
    78: "images/Lacteos y huevos/Queso campesino.webp",
    79: "images/Lacteos y huevos/Six pack Leche pomar entera.webp",
    80: "images/Lacteos y huevos/Six pack Leche deslactosada pomar.webp",
    81: "images/Lacteos y huevos/Leche pomar entera.webp",
    82: "images/Lacteos y huevos/Six pack leche entera alpina.webp",
    83: "images/Lacteos y huevos/Leche entera alpina.webp",
    84: "images/Lacteos y huevos/Queso parmesano alpina 100gr.webp",
    85: "images/Lacteos y huevos/Queso holandes alpina 450 gr.webp",
    86: "images/Lacteos y huevos/Mantequilla con sal alpina 125 gr.webp",
    87: "images/Despensa gourmet/Mantequilla clarificada orginal de fubafala.webp",
    88: "images/Despensa gourmet/Mantequilla clarificada orginal de fubafala 200 gr.webp",
    89: "images/Despensa gourmet/Mantequilla clarificada orginal de vaca 200 gr.webp",
}

with open("model.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    for pid, path in img.items():
        marker = f'"id": {pid},'
        if marker in line and '"imagen": ""' in line:
            line = line.replace('"imagen": ""', f'"imagen": "{path}"')
            break
    new_lines.append(line)

with open("model.py", "w", encoding="utf-8") as f:
    f.writelines(new_lines)

print("OK")
