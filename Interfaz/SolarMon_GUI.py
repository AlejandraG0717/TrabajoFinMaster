import tkinter as tk
from tkinter import scrolledtext, ttk, messagebox, filedialog
import time
import math
import csv
import os
from datetime import datetime
import paho.mqtt.client as mqtt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import numpy as np
try:
    from scipy.signal import savgol_filter
    _SCIPY_OK = True
except ImportError:
    _SCIPY_OK = False

# ══════════════════════════════════════════════════════════════
#  CONFIGURACIÓN MQTT
# ══════════════════════════════════════════════════════════════
BROKER   = "ff76cb3b60b24f868536ef946a66357e.s1.eu.hivemq.cloud"
PORT     = 8883
USERNAME = "Monisol1"
PASSWORD = "123456aA"

# ══════════════════════════════════════════════════════════════
#  PALETA DE COLORES
# ══════════════════════════════════════════════════════════════
COLORS = {
    'primary':   '#1e3a5f',
    'secondary': '#2c5282',
    'accent':    '#3182ce',
    'success':   '#38a169',
    'warning':   '#d69e2e',
    'danger':    '#e53e3e',
    'bg_light':  '#f7fafc',
    'bg_white':  '#ffffff',
    'text_dark': '#1a202c',
    'text_gray': '#718096',
    'border':    '#e2e8f0'
}

CALIBRACION = {
    'V_MODULE': 74.16,  
    'V23_MOD':   102.66,   
    'V13_MOD':   205.30,   
    'I_string':  167,  

    # Calibración para la curva IV (MONI_BJT_nuevo usa los pines VI e I_string,
    'VI_curva':       74.16,   
    'I_string_curva': 167,    
}

# ══════════════════════════════════════════════════════════════
#  VARIABLES GLOBALES
# ══════════════════════════════════════════════════════════════
pvsx               = "EMPTY"
topic_data         = ""
topic_config       = ""
topic_request      = ""
topic_status       = ""
topic_empty_status = "EMPTY/STATUS"
topic_empty_config = "EMPTY/CONFIG"

nodes              = {}
NODE_TIMEOUT_SECONDS = 60


iv_curvas      = {}    
iv_voltages    = []    
iv_currents    = []
op_point       = None
mpp_point      = None
iv_blocks      = {}
iv_total_blocks = 0
iv_tipo_pendiente = "MO"   

IV_COLORES = {
    "MO":   {"color": "steelblue",  "nombre": "Completo (MO)"},
    "MO23": {"color": "darkorange", "nombre": "2/3 módulo (MO23)"},
    "MO13": {"color": "seagreen",   "nombre": "1/3 módulo (MO13)"},
}

# Perturbación
perturb_resultados = {}

# Localización
locate_tablas      = {}   # {mac: {mac_vecino: rssi}}
locate_posiciones  = {}   # {mac: {x, y, pvsx, tipo}}
locate_cola        = []   # cola de MACs pendientes de LOCATE
locate_cola_idx    = 0    # índice actual en la cola
locate_en_curso    = False
LOCATE_DELAY_MS    = 3000 # ms entre envíos secuenciales

# Referencias manuales: [{mac, pvsx, x, y}]  (máx 3)
referencias = []

# ══════════════════════════════════════════════════════════════
#  VENTANA PRINCIPAL
# ══════════════════════════════════════════════════════════════
root = tk.Tk()
root.title("SolarMon - Sistema de Monitorización Fotovoltaica")
root.geometry("1400x800")
root.configure(bg=COLORS['bg_light'])
root.minsize(1200, 700)

style = ttk.Style()
style.theme_use('clam')

# Barra superior
header_frame = tk.Frame(root, bg=COLORS['primary'], height=60)
header_frame.pack(fill='x', side='top')
header_frame.pack_propagate(False)
tk.Label(header_frame,
         text="🔆 SolarMon - Monitorización de Plantas Fotovoltaicas",
         font=('Segoe UI', 14, 'bold'), bg=COLORS['primary'], fg='white'
         ).pack(side='left', padx=20, pady=10)
status_indicator = tk.Label(header_frame, text="● Desconectado",
                             font=('Segoe UI', 10), bg=COLORS['primary'],
                             fg=COLORS['danger'])
status_indicator.pack(side='right', padx=20, pady=10)

main_container = tk.Frame(root, bg=COLORS['bg_light'])
main_container.pack(fill='both', expand=True, padx=15, pady=15)

notebook = ttk.Notebook(main_container)
notebook.pack(fill='both', expand=True)

# ══════════════════════════════════════════════════════════════
#  HELPER: crear tarjeta visual
# ══════════════════════════════════════════════════════════════
def create_card(parent, title, row, col, rowspan=1, colspan=1, min_height=None):
    card = tk.Frame(parent, bg=COLORS['bg_white'],
                    highlightbackground=COLORS['border'], highlightthickness=1)
    card.grid(row=row, column=col, rowspan=rowspan, columnspan=colspan,
              padx=10, pady=10, sticky='nsew')
    if min_height:
        card.grid_propagate(False)
        card.configure(height=min_height)
    hdr = tk.Frame(card, bg=COLORS['secondary'], height=35)
    hdr.pack(fill='x', side='top')
    hdr.pack_propagate(False)
    tk.Label(hdr, text=title, font=('Segoe UI', 10, 'bold'),
             bg=COLORS['secondary'], fg='white').pack(side='left', padx=10, pady=5)
    content = tk.Frame(card, bg=COLORS['bg_white'])
    content.pack(fill='both', expand=True, padx=10, pady=10)
    return content, card

# ══════════════════════════════════════════════════════════════
#  PESTAÑA 1: PANEL DE CONTROL
# ══════════════════════════════════════════════════════════════
tab_dashboard = tk.Frame(notebook, bg=COLORS['bg_light'])
notebook.add(tab_dashboard, text="  📊 Panel de Control  ")

tab_dashboard.grid_columnconfigure(0, weight=1)
tab_dashboard.grid_columnconfigure(1, weight=2)
tab_dashboard.grid_columnconfigure(2, weight=2)
tab_dashboard.grid_rowconfigure(1, weight=1)

# ── Fila 0: Configuración ────────────────────────────────────
cfg_c, _ = create_card(tab_dashboard, "⚙️ Configuración del Nodo", 0, 0, colspan=3)
tk.Label(cfg_c, text="PVSx:", font=('Segoe UI',10), bg=COLORS['bg_white'],
         fg=COLORS['text_dark']).grid(row=0, column=0, sticky='w', pady=5)
entry_pvsx = tk.Entry(cfg_c, font=('Segoe UI',10), width=15,
                      highlightbackground=COLORS['border'], highlightthickness=1)
entry_pvsx.grid(row=0, column=1, padx=5, pady=5, sticky='w')
entry_pvsx.insert(0, "EMPTY")
tk.Label(cfg_c, text="MAC:", font=('Segoe UI',10), bg=COLORS['bg_white'],
         fg=COLORS['text_dark']).grid(row=0, column=2, sticky='w', padx=(20,0))
entry_mac = tk.Entry(cfg_c, font=('Segoe UI',10), width=18,
                     highlightbackground=COLORS['border'], highlightthickness=1)
entry_mac.grid(row=0, column=3, padx=5, pady=5, sticky='w')
tk.Button(cfg_c, text="Actualizar", command=lambda: update_pvsx(),
          font=('Segoe UI',9), bg=COLORS['accent'], fg='white',
          relief='flat', cursor='hand2').grid(row=0, column=4, padx=10)
tk.Label(cfg_c, text="EMPTY/CONFIG:", font=('Segoe UI',10), bg=COLORS['bg_white'],
         fg=COLORS['text_dark']).grid(row=1, column=0, sticky='w', pady=5)
entry_empty_config = tk.Entry(cfg_c, font=('Segoe UI',10), width=40,
                               highlightbackground=COLORS['border'], highlightthickness=1)
entry_empty_config.grid(row=1, column=1, columnspan=3, padx=5, pady=5, sticky='we')
tk.Button(cfg_c, text="Enviar", command=lambda: publish_empty_config(),
          font=('Segoe UI',9), bg=COLORS['success'], fg='white',
          relief='flat', cursor='hand2').grid(row=1, column=4, padx=10)

# ── Fila 1: Nodos ────────────────────────────────────────────
nodes_c, _ = create_card(tab_dashboard, "🌐 Nodos de la Red", 1, 0, min_height=280)
tree = ttk.Treeview(nodes_c, columns=("PVSx","MAC","Modo","Estado","Última vez"),
                    show='headings', height=8)
for col, w in [("PVSx",80),("MAC",130),("Modo",80),("Estado",80),("Última vez",100)]:
    tree.heading(col, text=col)
    tree.column(col, width=w, anchor='center')
tree.tag_configure('online',  background='#f0fff4', foreground='#276749')
tree.tag_configure('offline', background='#fff5f5', foreground='#c53030')
tree.tag_configure('gateway', background='#ebf8ff', foreground='#2c5282')
tree.tag_configure('directo', background='#fefcbf', foreground='#744210')
sb_tree = ttk.Scrollbar(nodes_c, orient='vertical', command=tree.yview)
tree.configure(yscrollcommand=sb_tree.set)
sb_tree.pack(side='right', fill='y')
tree.pack(fill='both', expand=True)
tk.Button(nodes_c, text="Limpiar desconectados",
          command=lambda: limpiar_desconectados(),
          font=('Segoe UI',8), bg=COLORS['danger'], fg='white',
          relief='flat', cursor='hand2').pack(pady=5)

# ── Fila 1 centro: Configuración ────────────────────────────
cmd_c, _ = create_card(tab_dashboard, "🔧 Comandos de Configuración", 1, 1)
tk.Label(cmd_c, text="Comando:", font=('Segoe UI',10), bg=COLORS['bg_white'],
         fg=COLORS['text_dark']).pack(anchor='w')
entry_pvsx_config = tk.Entry(cmd_c, font=('Segoe UI',10),
                              highlightbackground=COLORS['border'], highlightthickness=1)
entry_pvsx_config.pack(fill='x', pady=3)
btn_row1 = tk.Frame(cmd_c, bg=COLORS['bg_white'])
btn_row1.pack(fill='x', pady=3)
tk.Button(btn_row1, text="Enviar Comando", command=lambda: publish_pvsx_config(),
          font=('Segoe UI',9), bg=COLORS['secondary'], fg='white',
          relief='flat', cursor='hand2').pack(side='left')
tk.Button(btn_row1, text="✕ Limpiar LOG",
          command=lambda: text_area_pvsx_config.delete('1.0', tk.END),
          font=('Segoe UI',9), bg=COLORS['text_gray'], fg='white',
          relief='flat', cursor='hand2').pack(side='right')
text_area_pvsx_config = scrolledtext.ScrolledText(cmd_c, height=6,
    font=('Courier',9), bg=COLORS['bg_light'], fg='#072A3E',
    insertbackground='white', borderwidth=0)
text_area_pvsx_config.pack(fill='both', expand=True, pady=3)
status_hdr = tk.Frame(cmd_c, bg=COLORS['bg_white'])
status_hdr.pack(fill='x', pady=(8,2))
tk.Label(status_hdr, text="Respuestas STATUS:", font=('Segoe UI',10,'bold'),
         bg=COLORS['bg_white'], fg=COLORS['text_dark']).pack(side='left')
tk.Button(status_hdr, text="✕ Limpiar",
          command=lambda: text_area_status.delete('1.0', tk.END),
          font=('Segoe UI',8), bg=COLORS['text_gray'], fg='white',
          relief='flat', cursor='hand2', padx=6).pack(side='right')
text_area_status = scrolledtext.ScrolledText(cmd_c, height=6,
    font=('Courier',9), bg= COLORS['bg_light'], fg="#072A3E",
    insertbackground='white', borderwidth=0)
text_area_status.pack(fill='both', expand=True)

# ── Fila 1 derecha: Medición ─────────────────────────────────
med_c, _ = create_card(tab_dashboard, "📡 Comandos de Medición", 1, 2)
tk.Label(med_c, text="Solicitud:", font=('Segoe UI',10), bg=COLORS['bg_white'],
         fg=COLORS['text_dark']).pack(anchor='w')
entry_pvsx_request = tk.Entry(med_c, font=('Segoe UI',10),
                               highlightbackground=COLORS['border'], highlightthickness=1)
entry_pvsx_request.pack(fill='x', pady=3)
btn_row2 = tk.Frame(med_c, bg=COLORS['bg_white'])
btn_row2.pack(fill='x', pady=3)
tk.Button(btn_row2, text="Enviar Solicitud", command=lambda: publish_pvsx_request(),
          font=('Segoe UI',9), bg=COLORS['secondary'], fg='white',
          relief='flat', cursor='hand2').pack(side='left')
tk.Button(btn_row2, text="✕ Limpiar LOG",
          command=lambda: text_area_pvsx_request.delete('1.0', tk.END),
          font=('Segoe UI',9), bg=COLORS['text_gray'], fg='white',
          relief='flat', cursor='hand2').pack(side='right')
text_area_pvsx_request = scrolledtext.ScrolledText(med_c, height=6,
    font=('Courier',9), bg=COLORS['bg_light'], fg='#072A3E',
    insertbackground='white', borderwidth=0)
text_area_pvsx_request.pack(fill='both', expand=True, pady=3)
data_hdr = tk.Frame(med_c, bg=COLORS['bg_white'])
data_hdr.pack(fill='x', pady=(8,2))
tk.Label(data_hdr, text="Datos de Medición (DATA):", font=('Segoe UI',10,'bold'),
         bg=COLORS['bg_white'], fg=COLORS['text_dark']).pack(side='left')
tk.Button(data_hdr, text="✕ Limpiar",
          command=lambda: text_area_data.delete('1.0', tk.END),
          font=('Segoe UI',8), bg=COLORS['text_gray'], fg='white',
          relief='flat', cursor='hand2', padx=6).pack(side='right')
text_area_data = scrolledtext.ScrolledText(med_c, height=6,
    font=('Courier',9), bg=COLORS['bg_light'], fg='#072A3E',
    insertbackground='white', borderwidth=0)
text_area_data.pack(fill='both', expand=True)

# Fila 2: EMPTY/STATUS y CONFIG respuestas
tab_dashboard.grid_rowconfigure(2, weight=0)
emp_c, _ = create_card(tab_dashboard, "📋 EMPTY/STATUS & CONFIG", 2, 0, colspan=3)
emp_c.grid_columnconfigure(0, weight=1)
emp_c.grid_columnconfigure(1, weight=1)
text_area_empty_status = scrolledtext.ScrolledText(emp_c, height=4,
    font=('Courier',9), bg=COLORS['bg_light'], fg="#290254",
    insertbackground='white', borderwidth=0)
text_area_empty_status.grid(row=0, column=0, sticky='nsew', padx=5)
text_area_empty_config = scrolledtext.ScrolledText(emp_c, height=4,
    font=('Courier',9), bg=COLORS['bg_light'], fg="#072A3E",
    insertbackground='white', borderwidth=0)
text_area_empty_config.grid(row=0, column=1, sticky='nsew', padx=5)

# ══════════════════════════════════════════════════════════════
#  PESTAÑA 2: CURVA IV
# ══════════════════════════════════════════════════════════════
tab_iv_curve = tk.Frame(notebook, bg=COLORS['bg_light'])
notebook.add(tab_iv_curve, text="  📈 Curva IV  ")

tab_iv_curve.grid_columnconfigure(0, weight=3)   
tab_iv_curve.grid_columnconfigure(1, weight=2)  
tab_iv_curve.grid_rowconfigure(1, weight=1)

# ── Header ───────────────────────────────────────────────────
iv_hdr = tk.Frame(tab_iv_curve, bg=COLORS['secondary'], height=40)
iv_hdr.grid(row=0, column=0, columnspan=2, sticky='ew', padx=10, pady=(10,0))
iv_hdr.grid_propagate(False)
tk.Label(iv_hdr, text="📈 Curva IV — Punto OP y MPP",
         font=('Segoe UI',12,'bold'), bg=COLORS['secondary'], fg='white'
         ).pack(side='left', padx=15, pady=8)
label_node_info = tk.Label(iv_hdr, text="Nodo: ---",
                            font=('Segoe UI',10), bg=COLORS['secondary'], fg='#bee3f8')
label_node_info.pack(side='left', padx=15)
tk.Button(iv_hdr, text="🗑 Limpiar", command=lambda: limpiar_grafica(),
          font=('Segoe UI',9), bg=COLORS['danger'], fg='white',
          relief='flat', cursor='hand2').pack(side='right', padx=6)
tk.Button(iv_hdr, text="💾 Exportar CSV", command=lambda: exportar_iv_csv(),
          font=('Segoe UI',9), bg=COLORS['success'], fg='white',
          relief='flat', cursor='hand2').pack(side='right', padx=6)

var_comparar_iv = tk.BooleanVar(value=True)
tk.Checkbutton(iv_hdr, text="Comparar MO/MO23/MO13", variable=var_comparar_iv,
               command=lambda: redibujar_iv(),
               font=('Segoe UI',9), bg=COLORS['secondary'], fg='white',
               selectcolor=COLORS['secondary'], activebackground=COLORS['secondary'],
               activeforeground='white').pack(side='right', padx=10)

# ── Columna izquierda: gráfica IV principal ───────────────────
iv_main = tk.Frame(tab_iv_curve, bg=COLORS['bg_white'],
                   highlightbackground=COLORS['border'], highlightthickness=1)
iv_main.grid(row=1, column=0, sticky='nsew', padx=(10,4), pady=10)
iv_main.grid_rowconfigure(0, weight=1)
iv_main.grid_columnconfigure(0, weight=1)

fig_iv = Figure(figsize=(6.5, 4.2), dpi=100)
ax_iv  = fig_iv.add_subplot(111)
ax_iv.set_title("Curva IV")
ax_iv.set_xlabel("Voltaje (V)")
ax_iv.set_ylabel("Corriente (A)")
ax_iv.grid(True, linestyle='--', alpha=0.5)
canvas_iv = FigureCanvasTkAgg(fig_iv, master=iv_main)
canvas_iv.draw()
canvas_iv.get_tk_widget().grid(row=0, column=0, sticky='nsew', padx=8, pady=8)

vals_frame = tk.Frame(iv_main, bg=COLORS['bg_white'])
vals_frame.grid(row=1, column=0, sticky='ew', padx=10, pady=4)
tk.Label(vals_frame, text="Curva IV:", font=('Segoe UI',9,'bold'),
         bg=COLORS['bg_white'], fg=COLORS['text_dark']).grid(row=0,column=0,padx=6)
lbl_iv_puntos = tk.Label(vals_frame, text="— puntos", font=('Segoe UI',9),
                          bg=COLORS['bg_white'], fg=COLORS['text_gray'])
lbl_iv_puntos.grid(row=0, column=1, padx=6)
tk.Label(vals_frame, text="OP:", font=('Segoe UI',9,'bold'),
         bg=COLORS['bg_white'], fg='red').grid(row=0,column=2,padx=6)
lbl_op = tk.Label(vals_frame, text="V=---  I=---", font=('Segoe UI',9),
                   bg=COLORS['bg_white'], fg=COLORS['text_gray'])
lbl_op.grid(row=0, column=3, padx=6)
tk.Label(vals_frame, text="MPP:", font=('Segoe UI',9,'bold'),
         bg=COLORS['bg_white'], fg='darkorange').grid(row=0,column=4,padx=6)
lbl_mpp = tk.Label(vals_frame, text="V=---  I=---  P=---", font=('Segoe UI',9),
                    bg=COLORS['bg_white'], fg=COLORS['text_gray'])
lbl_mpp.grid(row=0, column=5, padx=6)

# ── Columna derecha: V y I por separado ───────────────────────
iv_right = tk.Frame(tab_iv_curve, bg=COLORS['bg_white'],
                    highlightbackground=COLORS['border'], highlightthickness=1)
iv_right.grid(row=1, column=1, sticky='nsew', padx=(4,10), pady=10)
iv_right.grid_rowconfigure(0, weight=1)
iv_right.grid_rowconfigure(1, weight=1)
iv_right.grid_columnconfigure(0, weight=1)

# Subgráfica Voltaje
fig_v = Figure(figsize=(4, 2.0), dpi=100)
fig_v.subplots_adjust(left=0.18, right=0.97, top=0.87, bottom=0.22)
ax_v  = fig_v.add_subplot(111)
ax_v.set_title("Voltaje vs. Muestra", fontsize=9)
ax_v.set_xlabel("Muestra", fontsize=8)
ax_v.set_ylabel("V (V)", fontsize=8)
ax_v.tick_params(labelsize=7)
ax_v.grid(True, linestyle='--', alpha=0.4)
canvas_v = FigureCanvasTkAgg(fig_v, master=iv_right)
canvas_v.draw()
canvas_v.get_tk_widget().grid(row=0, column=0, sticky='nsew', padx=6, pady=(8,2))

# Subgráfica Corriente
fig_i = Figure(figsize=(4, 2.0), dpi=100)
fig_i.subplots_adjust(left=0.18, right=0.97, top=0.87, bottom=0.22)
ax_i  = fig_i.add_subplot(111)
ax_i.set_title("Corriente vs. Muestra", fontsize=9)
ax_i.set_xlabel("Muestra", fontsize=8)
ax_i.set_ylabel("I (A)", fontsize=8)
ax_i.tick_params(labelsize=7)
ax_i.grid(True, linestyle='--', alpha=0.4)
canvas_i = FigureCanvasTkAgg(fig_i, master=iv_right)
canvas_i.draw()
canvas_i.get_tk_widget().grid(row=1, column=0, sticky='nsew', padx=6, pady=(2,8))

# ══════════════════════════════════════════════════════════════
#  PESTAÑA 3: PERTURBACIÓN
# ══════════════════════════════════════════════════════════════
tab_perturb = tk.Frame(notebook, bg=COLORS['bg_light'])
notebook.add(tab_perturb, text="  ⚡ Perturbación  ")
tab_perturb.grid_columnconfigure(0, weight=1)
tab_perturb.grid_rowconfigure(1, weight=1)

p_hdr = tk.Frame(tab_perturb, bg=COLORS['secondary'], height=40)
p_hdr.grid(row=0, column=0, sticky='ew', padx=10, pady=(10,0))
p_hdr.grid_propagate(False)
tk.Label(p_hdr, text="⚡ Localización de Tarjetas por Perturbación Eléctrica",
         font=('Segoe UI',12,'bold'), bg=COLORS['secondary'], fg='white'
         ).pack(side='left', padx=15, pady=8)

p_main = tk.Frame(tab_perturb, bg=COLORS['bg_white'],
                   highlightbackground=COLORS['border'], highlightthickness=1)
p_main.grid(row=1, column=0, sticky='nsew', padx=10, pady=10)
p_main.grid_columnconfigure(0, weight=1)
p_main.grid_columnconfigure(1, weight=1)
p_main.grid_rowconfigure(1, weight=1)

instr = tk.Frame(p_main, bg=COLORS['bg_light'],
                  highlightbackground=COLORS['border'], highlightthickness=1)
instr.grid(row=0, column=0, columnspan=2, sticky='ew', padx=10, pady=10)
tk.Label(instr,
         text="En un string serie todos comparten la misma corriente.\n"
              "El inyector activa DescargaA en tren de pulsos. Los oyentes muestrean PIN_VI.\n"
              "Si un nodo NO detecta → ruptura eléctrica entre él y el inyector.",
         font=('Segoe UI',9), bg=COLORS['bg_light'], fg=COLORS['text_gray'],
         justify='left').pack(padx=10, pady=8, anchor='w')

p_cmd = tk.Frame(p_main, bg=COLORS['bg_white'])
p_cmd.grid(row=1, column=0, sticky='nsew', padx=10, pady=5)

tk.Label(p_cmd, text="Nodo INYECTOR (MAC):", font=('Segoe UI',10,'bold'),
         bg=COLORS['bg_white'], fg=COLORS['text_dark']).pack(anchor='w', pady=(10,2))
entry_perturb_tx = tk.Entry(p_cmd, font=('Segoe UI',10), width=22,
                             highlightbackground=COLORS['border'], highlightthickness=1)
entry_perturb_tx.pack(fill='x', pady=2)
tk.Label(p_cmd, text="(se rellena con la MAC activa)",
         font=('Segoe UI',8), bg=COLORS['bg_white'], fg=COLORS['text_gray']
         ).pack(anchor='w')

tk.Label(p_cmd, text="Nodos OYENTES (MACs por coma o vacío = todos):",
         font=('Segoe UI',10,'bold'), bg=COLORS['bg_white'],
         fg=COLORS['text_dark']).pack(anchor='w', pady=(15,2))
entry_perturb_rx = tk.Entry(p_cmd, font=('Segoe UI',10), width=40,
                             highlightbackground=COLORS['border'], highlightthickness=1)
entry_perturb_rx.pack(fill='x', pady=2)

p_btns = tk.Frame(p_cmd, bg=COLORS['bg_white'])
p_btns.pack(fill='x', pady=15)
tk.Button(p_btns, text="⚡ Iniciar Perturbación", command=lambda: enviar_perturb(),
          font=('Segoe UI',10,'bold'), bg=COLORS['warning'], fg='white',
          relief='flat', cursor='hand2').pack(side='left', padx=5, ipady=4)
tk.Button(p_btns, text="🗑️ Limpiar", command=lambda: limpiar_perturb(),
          font=('Segoe UI',9), bg='#718096', fg='white',
          relief='flat', cursor='hand2').pack(side='left', padx=5, ipady=4)
tk.Button(p_btns, text="← MAC activa", command=lambda: (
    entry_perturb_tx.delete(0, tk.END),
    entry_perturb_tx.insert(0, entry_mac.get().strip())),
          font=('Segoe UI',9), bg=COLORS['accent'], fg='white',
          relief='flat', cursor='hand2').pack(side='right', padx=5)

p_res = tk.Frame(p_main, bg=COLORS['bg_white'])
p_res.grid(row=1, column=1, sticky='nsew', padx=10, pady=5)
tk.Label(p_res, text="Resultados de detección:", font=('Segoe UI',10,'bold'),
         bg=COLORS['bg_white'], fg=COLORS['text_dark']).pack(anchor='w', pady=(10,5))
tree_perturb = ttk.Treeview(p_res,
    columns=("PVSx","MAC","Estado","Magnitud ADC"), show='headings', height=12)
for col, w in [("PVSx",70),("MAC",140),("Estado",130),("Magnitud ADC",100)]:
    tree_perturb.heading(col, text=col)
    tree_perturb.column(col, width=w, anchor='center')
tree_perturb.tag_configure("tx", background="#fefcbf", foreground="#744210")
tree_perturb.tag_configure("si", background="#c6f6d5", foreground="#22543d")
tree_perturb.tag_configure("no", background="#fed7d7", foreground="#742a2a")
sb_p = ttk.Scrollbar(p_res, orient='vertical', command=tree_perturb.yview)
tree_perturb.configure(yscrollcommand=sb_p.set)
sb_p.pack(side='right', fill='y')
tree_perturb.pack(side='left', fill='both', expand=True)

p_leg = tk.Frame(p_main, bg=COLORS['bg_white'])
p_leg.grid(row=2, column=0, columnspan=2, sticky='ew', padx=10, pady=(0,10))
for txt, col in [("⚡ INYECTOR","#744210"),("✅ DETECTADO","#22543d"),
                 ("❌ NO DETECTADO","#742a2a")]:
    tk.Label(p_leg, text=txt, font=('Segoe UI',9),
             bg=COLORS['bg_white'], fg=col).pack(side='left', padx=12)

# ══════════════════════════════════════════════════════════════
#  PESTAÑA 4: LOCALIZACIÓN
# ══════════════════════════════════════════════════════════════
tab_locate = tk.Frame(notebook, bg=COLORS['bg_light'])
notebook.add(tab_locate, text="  📍 Localización  ")
tab_locate.grid_columnconfigure(0, weight=1)
tab_locate.grid_rowconfigure(2, weight=1)

# ── Header ────────────────────────────────────────────────────
loc_hdr = tk.Frame(tab_locate, bg=COLORS['secondary'], height=40)
loc_hdr.grid(row=0, column=0, sticky='ew', padx=10, pady=(10,0))
loc_hdr.grid_propagate(False)
tk.Label(loc_hdr, text="📍 Localización de Nodos por Trilateración RSSI",
         font=('Segoe UI',12,'bold'), bg=COLORS['secondary'], fg='white'
         ).pack(side='left', padx=15, pady=8)

lbl_locate_estado = tk.Label(loc_hdr, text="",
    font=('Segoe UI',10), bg=COLORS['secondary'], fg='#fbd38d')
lbl_locate_estado.pack(side='right', padx=15)

# ── Panel de parámetros ────────────────────────────────────────
loc_params = tk.Frame(tab_locate, bg=COLORS['bg_white'],
                       highlightbackground=COLORS['border'], highlightthickness=1)
loc_params.grid(row=1, column=0, sticky='ew', padx=10, pady=5)

# Fila de calibración
cal_row = tk.Frame(loc_params, bg=COLORS['bg_white'])
cal_row.pack(fill='x', padx=10, pady=6)

def lbl_p(parent, text):
    return tk.Label(parent, text=text, font=('Segoe UI',9,'bold'),
                    bg=COLORS['bg_white'], fg=COLORS['text_dark'])
def ent_p(parent, default, width=7):
    e = tk.Entry(parent, font=('Segoe UI',10), width=width,
                 highlightbackground=COLORS['border'], highlightthickness=1)
    e.insert(0, default)
    return e

lbl_p(cal_row, "RSSI 1m (dBm):").pack(side='left', padx=(0,2))
entry_rssi_1m = ent_p(cal_row, "-40"); entry_rssi_1m.pack(side='left', padx=(0,12))
lbl_p(cal_row, "Factor n:").pack(side='left', padx=(0,2))
entry_factor_n = ent_p(cal_row, "2.0"); entry_factor_n.pack(side='left', padx=(0,12))

tk.Button(cal_row, text="📍 Iniciar LOCATE (secuencial)",
          command=lambda: iniciar_locate_secuencial(),
          font=('Segoe UI',10,'bold'), bg=COLORS['secondary'], fg='white',
          relief='flat', cursor='hand2').pack(side='left', padx=8, ipady=4)
tk.Button(cal_row, text="🔄 Recalcular",
          command=lambda: calcular_posiciones(),
          font=('Segoe UI',9), bg=COLORS['accent'], fg='white',
          relief='flat', cursor='hand2').pack(side='left', padx=4, ipady=4)
tk.Button(cal_row, text="💾 Exportar CSV",
          command=lambda: exportar_csv(),
          font=('Segoe UI',9), bg='#276749', fg='white',
          relief='flat', cursor='hand2').pack(side='left', padx=4, ipady=4)
tk.Button(cal_row, text="🗑 Limpiar",
          command=lambda: limpiar_locate(),
          font=('Segoe UI',9), bg=COLORS['text_gray'], fg='white',
          relief='flat', cursor='hand2').pack(side='left', padx=4, ipady=4)

# Fila de referencias manuales
ref_outer = tk.Frame(loc_params, bg=COLORS['bg_white'])
ref_outer.pack(fill='x', padx=10, pady=(0,8))
tk.Label(ref_outer, text="Puntos de referencia (posición conocida — máx 3):",
         font=('Segoe UI',9,'bold'), bg=COLORS['bg_white'],
         fg=COLORS['text_dark']).pack(anchor='w', pady=(4,4))

ref_table_frame = tk.Frame(ref_outer, bg=COLORS['bg_white'])
ref_table_frame.pack(fill='x')

# Cabecera de la tabla de referencias
for i, (txt, w) in enumerate([("#",3),("PVSx/ID",10),("MAC",20),
                                ("X (m)",8),("Y (m)",8)]):
    tk.Label(ref_table_frame, text=txt, font=('Segoe UI',9,'bold'),
             bg=COLORS['border'], fg=COLORS['text_dark'],
             width=w, relief='flat', borderwidth=1
             ).grid(row=0, column=i, padx=1, pady=1, sticky='nsew')

ref_entries = []  # lista de {pvsx, mac, x, y} Entry widgets
for row_i in range(3):
    row_entries = {}
    for col_i, (key, w, default) in enumerate([
        ("num", 3, str(row_i+1)),
        ("pvsx", 10, ""),
        ("mac",  20, ""),
        ("x",     8, "0"),
        ("y",     8, "0"),
    ]):
        if key == "num":
            tk.Label(ref_table_frame, text=default, font=('Segoe UI',9),
                     bg=COLORS['bg_white'], width=w
                     ).grid(row=row_i+1, column=col_i, padx=1, pady=1)
        else:
            e = tk.Entry(ref_table_frame, font=('Segoe UI',9), width=w,
                         highlightbackground=COLORS['border'], highlightthickness=1)
            e.grid(row=row_i+1, column=col_i, padx=1, pady=1, sticky='nsew')
            row_entries[key] = e
    ref_entries.append(row_entries)

tk.Label(ref_table_frame,
         text="  Fila 1 = gateway/router (obligatoria). Filas 2-3 opcionales.",
         font=('Segoe UI',8), bg=COLORS['bg_white'], fg=COLORS['text_gray']
         ).grid(row=4, column=0, columnspan=5, sticky='w', padx=4, pady=2)

# ── Sub-notebook con 3 vistas ─────────────────────────────────
loc_nb = ttk.Notebook(tab_locate)
loc_nb.grid(row=2, column=0, sticky='nsew', padx=10, pady=5)

tab_mapa = tk.Frame(loc_nb, bg=COLORS['bg_white'])
tab_pos  = tk.Frame(loc_nb, bg=COLORS['bg_white'])
tab_raw  = tk.Frame(loc_nb, bg=COLORS['bg_white'])
loc_nb.add(tab_mapa, text="  🗺️ Mapa Visual  ")
loc_nb.add(tab_pos,  text="  📋 Posiciones Calculadas  ")
loc_nb.add(tab_raw,  text="  📊 Datos RSSI Crudos  ")

# Mapa
canvas_mapa = tk.Canvas(tab_mapa, bg="white",
                         highlightbackground=COLORS['border'], highlightthickness=1)
canvas_mapa.pack(fill='both', expand=True, padx=5, pady=5)
leg_mapa = tk.Frame(tab_mapa, bg=COLORS['bg_white'])
leg_mapa.pack(fill='x', padx=5, pady=(0,5))
for txt, col in [("🔷 Referencia fija","#2b6cb0"),
                 ("🟢 Calculado","#276749"),
                 ("⚫ Sin datos suficientes","#718096")]:
    tk.Label(leg_mapa, text=txt, font=('Segoe UI',8),
             bg=COLORS['bg_white'], fg=col).pack(side='left', padx=10)

# Tabla posiciones
pos_f = tk.Frame(tab_pos, bg=COLORS['bg_white'])
pos_f.pack(fill='both', expand=True, padx=5, pady=5)
tree_locate_pos = ttk.Treeview(pos_f,
    columns=("PVSx","MAC","X","Y","RSSI_Router","Tipo"), show='headings', height=15)
for col, w in [("PVSx",80),("MAC",145),("X",80),("Y",80),
               ("RSSI_Router",110),("Tipo",110)]:
    tree_locate_pos.heading(col, text=col)
    tree_locate_pos.column(col, width=w, anchor='center')
tree_locate_pos.tag_configure("ref",  background="#bee3f8", foreground="#2a4365")
tree_locate_pos.tag_configure("calc", background="#c6f6d5", foreground="#22543d")
tree_locate_pos.tag_configure("nop",  background="#fed7d7", foreground="#742a2a")
sb_pos = ttk.Scrollbar(pos_f, orient='vertical', command=tree_locate_pos.yview)
tree_locate_pos.configure(yscrollcommand=sb_pos.set)
sb_pos.pack(side='right', fill='y')
tree_locate_pos.pack(fill='both', expand=True)

# Tabla RSSI cruda
raw_f = tk.Frame(tab_raw, bg=COLORS['bg_white'])
raw_f.pack(fill='both', expand=True, padx=5, pady=5)
tree_locate_raw = ttk.Treeview(raw_f,
    columns=("PVSx","MAC_Origen","Vecino","RSSI","Distancia"), show='headings', height=15)
for col, w in [("PVSx",80),("MAC_Origen",145),("Vecino",160),
               ("RSSI",90),("Distancia",120)]:
    tree_locate_raw.heading(col, text=col)
    tree_locate_raw.column(col, width=w, anchor='center')
sb_raw = ttk.Scrollbar(raw_f, orient='vertical', command=tree_locate_raw.yview)
tree_locate_raw.configure(yscrollcommand=sb_raw.set)
sb_raw.pack(side='right', fill='y')
tree_locate_raw.pack(fill='both', expand=True)

# ══════════════════════════════════════════════════════════════
#  PESTAÑA 5: TOPOLOGÍA DE LA MALLA
# ══════════════════════════════════════════════════════════════
tab_topo = tk.Frame(notebook, bg=COLORS['bg_light'])
notebook.add(tab_topo, text="  🕸️ Topología Malla  ")
tab_topo.grid_columnconfigure(0, weight=1)
tab_topo.grid_columnconfigure(1, weight=1)
tab_topo.grid_rowconfigure(1, weight=1)

# Header
topo_hdr = tk.Frame(tab_topo, bg=COLORS['secondary'], height=40)
topo_hdr.grid(row=0, column=0, columnspan=2, sticky='ew', padx=10, pady=(10,0))
topo_hdr.grid_propagate(False)
tk.Label(topo_hdr, text="🕸️ Topología de la Malla Mesh",
         font=('Segoe UI',12,'bold'), bg=COLORS['secondary'], fg='white'
         ).pack(side='left', padx=15, pady=8)
lbl_topo_ts = tk.Label(topo_hdr, text="Sin datos",
    font=('Segoe UI',9), bg=COLORS['secondary'], fg='#bee3f8')
lbl_topo_ts.pack(side='right', padx=15)

# ── Columna izquierda: resumen del gateway + tabla de nodos ──
topo_left = tk.Frame(tab_topo, bg=COLORS['bg_white'],
                     highlightbackground=COLORS['border'], highlightthickness=1)
topo_left.grid(row=1, column=0, sticky='nsew', padx=(10,5), pady=10)
topo_left.grid_rowconfigure(2, weight=1)
topo_left.grid_columnconfigure(0, weight=1)

# Tarjeta resumen gateway
gw_title = tk.Frame(topo_left, bg=COLORS['secondary'], height=30)
gw_title.grid(row=0, column=0, sticky='ew')
gw_title.grid_propagate(False)
tk.Label(gw_title, text="Gateway activo", font=('Segoe UI',9,'bold'),
         bg=COLORS['secondary'], fg='white').pack(side='left', padx=10, pady=4)

gw_info = tk.Frame(topo_left, bg=COLORS['bg_light'],
                   highlightbackground=COLORS['border'], highlightthickness=1)
gw_info.grid(row=1, column=0, sticky='ew', padx=8, pady=8)

def _gw_lbl(parent, title, var_name):
    f = tk.Frame(parent, bg=COLORS['bg_light'])
    f.pack(side='left', padx=12, pady=6)
    tk.Label(f, text=title, font=('Segoe UI',8), bg=COLORS['bg_light'],
             fg=COLORS['text_gray']).pack()
    lbl = tk.Label(f, text="---", font=('Segoe UI',11,'bold'),
                   bg=COLORS['bg_light'], fg=COLORS['primary'])
    lbl.pack()
    return lbl

lbl_gw_id   = _gw_lbl(gw_info, "Nodo Gateway",  "id")
lbl_gw_rssi = _gw_lbl(gw_info, "RSSI WiFi",     "rssi")
lbl_gw_ip   = _gw_lbl(gw_info, "IP",            "ip")
lbl_gw_modo = _gw_lbl(gw_info, "Modo",          "modo")
lbl_gw_nnodos = _gw_lbl(gw_info, "Nodos malla", "n")

# Tabla de nodos de la malla
nodos_title = tk.Frame(topo_left, bg=COLORS['secondary'], height=28)
nodos_title.grid(row=2, column=0, sticky='new')
nodos_title.grid_propagate(False)
tk.Label(nodos_title, text="Nodos registrados en la malla",
         font=('Segoe UI',9,'bold'), bg=COLORS['secondary'], fg='white'
         ).pack(side='left', padx=10, pady=3)

tree_topo = ttk.Treeview(topo_left,
    columns=("Nombre","MeshID","RSSI","Modo","GW","Activo","Inactivo"),
    show='headings', height=12)
for col, w in [("Nombre",130),("MeshID",90),("RSSI",70),
               ("Modo",80),("GW",40),("Activo",60),("Inactivo",90)]:
    tree_topo.heading(col, text=col)
    tree_topo.column(col, width=w, anchor='center')
tree_topo.tag_configure("gw",     background="#ebf8ff", foreground="#2c5282")
tree_topo.tag_configure("activo", background="#f0fff4", foreground="#276749")
tree_topo.tag_configure("inact",  background="#fff5f5", foreground="#c53030")
sb_topo = ttk.Scrollbar(topo_left, orient='vertical', command=tree_topo.yview)
tree_topo.configure(yscrollcommand=sb_topo.set)

topo_left.grid_rowconfigure(3, weight=1)
sb_topo.grid(row=3, column=1, sticky='ns', pady=(0,8))
tree_topo.grid(row=3, column=0, sticky='nsew', padx=(8,0), pady=(0,8))

# ── Columna derecha: mapa visual de la malla ──
topo_right = tk.Frame(tab_topo, bg=COLORS['bg_white'],
                      highlightbackground=COLORS['border'], highlightthickness=1)
topo_right.grid(row=1, column=1, sticky='nsew', padx=(5,10), pady=10)
topo_right.grid_rowconfigure(1, weight=1)
topo_right.grid_columnconfigure(0, weight=1)

map_title = tk.Frame(topo_right, bg=COLORS['secondary'], height=30)
map_title.grid(row=0, column=0, sticky='ew')
map_title.grid_propagate(False)
tk.Label(map_title, text="Mapa de la malla (RSSI relativo)",
         font=('Segoe UI',9,'bold'), bg=COLORS['secondary'], fg='white'
         ).pack(side='left', padx=10, pady=4)

canvas_topo = tk.Canvas(topo_right, bg='#0f172a',
                         highlightbackground=COLORS['border'], highlightthickness=0)
canvas_topo.grid(row=1, column=0, sticky='nsew', padx=8, pady=8)

# Leyenda mapa
leg_topo = tk.Frame(topo_right, bg=COLORS['bg_white'])
leg_topo.grid(row=2, column=0, sticky='ew', padx=8, pady=(0,6))
for txt, col in [("🟦 Gateway","#60a5fa"), ("🟢 Nodo activo","#4ade80"),
                 ("🔴 Inactivo","#f87171")]:
    tk.Label(leg_topo, text=txt, font=('Segoe UI',8),
             bg=COLORS['bg_white'], fg=COLORS['text_dark']).pack(side='left', padx=8)

# ══════════════════════════════════════════════════════════════
#  PESTAÑA 6: LOGS
# ══════════════════════════════════════════════════════════════
tab_logs = tk.Frame(notebook, bg=COLORS['bg_light'])
notebook.add(tab_logs, text="  📝 Logs del Sistema  ")
tab_logs.grid_columnconfigure(0, weight=1)
tab_logs.grid_rowconfigure(0, weight=1)
log_c, _ = create_card(tab_logs, "📝 Log completo de mensajes MQTT", 0, 0)
text_log = scrolledtext.ScrolledText(log_c, font=('Courier',9),
                                      bg='#1a202c', fg='#a0aec0',
                                      insertbackground='white', borderwidth=0)
text_log.pack(fill='both', expand=True)
tk.Button(log_c, text="Limpiar log",
          command=lambda: text_log.delete('1.0', tk.END),
          font=('Segoe UI',9), bg=COLORS['text_gray'], fg='white',
          relief='flat').pack(pady=4)

# ══════════════════════════════════════════════════════════════
#  FUNCIONES DE GRÁFICA IV
# ══════════════════════════════════════════════════════════════
def redibujar_iv():
    # ── Gráfica IV principal ──────────────────────────────────
    ax_iv.clear()
    ax_iv.set_title("Curva IV — " + pvsx)
    ax_iv.set_xlabel("Voltaje (V)")
    ax_iv.set_ylabel("Corriente (A)")
    ax_iv.grid(True, linestyle='--', alpha=0.5)

    comparar = var_comparar_iv.get() if 'var_comparar_iv' in globals() else False

    if comparar:
        for tipo, datos in iv_curvas.items():
            v, i = datos.get("v", []), datos.get("i", [])
            if v and i:
                cfg = IV_COLORES.get(tipo, {"color": "gray", "nombre": tipo})
                ax_iv.plot(v, i, color=cfg["color"], linewidth=1.5,
                           marker='.', markersize=4, label=cfg["nombre"])
    else:
        if iv_voltages and iv_currents:
            ax_iv.plot(iv_voltages, iv_currents, color='steelblue',
                       linewidth=1.5, marker='.', markersize=4, label='Curva IV')

    if op_point:
        vop, iop = op_point
        ax_iv.plot(vop, iop, marker='v', color='red', markersize=10,
                   zorder=5, label=f'OP ({vop:.2f}V,{iop:.3f}A)')
    if mpp_point:
        vm, im, pm = mpp_point
        ax_iv.plot(vm, im, marker='*', color='darkorange', markersize=14,
                   zorder=5, label=f'MPP ({vm:.2f}V,{im:.3f}A) P={pm:.2f}W')
    if iv_voltages or op_point or mpp_point or (comparar and iv_curvas):
        ax_iv.legend(loc='upper right', fontsize=8)
    canvas_iv.draw()

    # ── Gráfica Voltaje vs. muestra ───────────────────────────
    ax_v.clear()
    ax_v.set_title("Voltaje vs. Muestra", fontsize=9)
    ax_v.set_xlabel("Muestra", fontsize=8)
    ax_v.set_ylabel("V (V)", fontsize=8)
    ax_v.tick_params(labelsize=7)
    ax_v.grid(True, linestyle='--', alpha=0.4)
    if comparar:
        for tipo, datos in iv_curvas.items():
            v = datos.get("v", [])
            if v:
                cfg = IV_COLORES.get(tipo, {"color": "gray", "nombre": tipo})
                ax_v.plot(range(len(v)), v, color=cfg["color"],
                          linewidth=1.0, marker='.', markersize=2, label=cfg["nombre"])
        if iv_curvas:
            ax_v.legend(fontsize=6, loc='upper right')
    elif iv_voltages:
        ax_v.plot(range(len(iv_voltages)), iv_voltages,
                  color='#3182ce', linewidth=1.2, marker='.', markersize=3)
    canvas_v.draw()

    # ── Gráfica Corriente vs. muestra ─────────────────────────
    ax_i.clear()
    ax_i.set_title("Corriente vs. Muestra", fontsize=9)
    ax_i.set_xlabel("Muestra", fontsize=8)
    ax_i.set_ylabel("I (A)", fontsize=8)
    ax_i.tick_params(labelsize=7)
    ax_i.grid(True, linestyle='--', alpha=0.4)
    if comparar:
        for tipo, datos in iv_curvas.items():
            i_data = datos.get("i", [])
            if i_data:
                cfg = IV_COLORES.get(tipo, {"color": "gray", "nombre": tipo})
                ax_i.plot(range(len(i_data)), i_data, color=cfg["color"],
                          linewidth=1.0, marker='.', markersize=2, label=cfg["nombre"])
        if iv_curvas:
            ax_i.legend(fontsize=6, loc='upper right')
    elif iv_currents:
        ax_i.plot(range(len(iv_currents)), iv_currents,
                  color='#38a169', linewidth=1.2, marker='.', markersize=3)
    canvas_i.draw()

def exportar_iv_csv():
    """Exporta los datos de voltaje y corriente de la curva IV a un CSV."""
    if not iv_voltages or not iv_currents:
        messagebox.showwarning("Sin datos", "No hay datos de curva IV para exportar.")
        return
    path = filedialog.asksaveasfilename(
        title="Guardar curva IV como CSV",
        defaultextension=".csv",
        filetypes=[("CSV", "*.csv"), ("Todos", "*.*")],
        initialfile=f"curvaIV_{pvsx}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    )
    if not path:
        return
    try:
        with open(path, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            # Cabecera con metadatos
            w.writerow(["# SolarMon — Curva IV"])
            w.writerow(["# Nodo", pvsx])
            w.writerow(["# Fecha", datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
            w.writerow(["# Puntos", len(iv_voltages)])
            if mpp_point:
                w.writerow(["# MPP_V", f"{mpp_point[0]:.2f}",
                             "MPP_I", f"{mpp_point[1]:.2f}",
                             "MPP_P", f"{mpp_point[2]:.2f}"])
            if op_point:
                w.writerow(["# OP_V", f"{op_point[0]:.2f}",
                             "OP_I", f"{op_point[3]:.2f}"])
            w.writerow([])
            # Datos
            w.writerow(["muestra", "voltaje_V", "corriente_A"])
            for k, (v, i) in enumerate(zip(iv_voltages, iv_currents)):
                w.writerow([k, f"{v:.4f}", f"{i:.4f}"])
        _log_status(f"Curva IV exportada: {os.path.basename(path)}")
        messagebox.showinfo("Exportado", f"CSV guardado en:\n{path}")
    except Exception as e:
        messagebox.showerror("Error", f"No se pudo guardar el archivo:\n{e}")

def limpiar_grafica():
    global iv_voltages, iv_currents, op_point, mpp_point, iv_curvas
    iv_voltages = []; iv_currents = []; op_point = None; mpp_point = None
    iv_curvas = {}
    lbl_iv_puntos.config(text="— puntos")
    lbl_op.config(text="V=---  I=---")
    lbl_mpp.config(text="V=---  I=---  P=---")
    redibujar_iv()

def procesar_iv(payload):
    global iv_voltages, iv_currents
    parts = payload.strip().split("//")
    if len(parts) < 5: return
    iv_voltages = [float(x) for x in parts[3].strip().split(",") if x.strip()]
    iv_currents = [float(x) for x in parts[4].strip().split(",") if x.strip()]
    lbl_iv_puntos.config(text=f"{len(iv_voltages)} puntos")
    redibujar_iv(); notebook.select(tab_iv_curve)

def procesar_op(payload):
    global op_point
    parts = payload.strip().split("//")
    if len(parts) < 5: 
        return
    
    # Aplicar calibración a cada canal
    V_raw   = float(parts[3])
    V23_raw = float(parts[4])
    V13_raw = float(parts[5])
    I_raw   = float(parts[6])
    
    V   = V_raw   / CALIBRACION['V_MODULE']
    V23 = V23_raw / CALIBRACION['V23_MOD']
    V13 = V13_raw / CALIBRACION['V13_MOD']
    I   = I_raw   / CALIBRACION['I_string']
    
    op_point = (V, I)
    
    # Mostrar valores calibrados en la interfaz
    lbl_op.config(text=f"V={V:.2f}V  I={I:.3f}A")
    
    # Log con valores calibrados
    _log_status(f"OP calibrado: V={V:.2f}V, V23={V23:.2f}V, V13={V13:.2f}V, I={I:.3f}mA")
    
    redibujar_iv()
    notebook.select(tab_iv_curve)

def procesar_mpp(payload):
    global mpp_point
    parts = payload.strip().split("//")
    if len(parts) < 5: return
    vm_raw = float(parts[3]); im_raw = float(parts[4])

    fv = CALIBRACION.get('VI_curva', 1.0)
    fi = CALIBRACION.get('I_string_curva', 1.0)
    vm = vm_raw / fv
    im = im_raw / fi
    pm_raw = float(parts[5]) if len(parts) > 5 else vm_raw * im_raw
    pm = vm * im

    mpp_point = (vm, im, pm)
    lbl_mpp.config(text=f"V={vm:.2f}V  I={im:.3f}A  P={pm:.2f}W")
    redibujar_iv(); notebook.select(tab_iv_curve)

def calibrar_curva_iv(v_raw, i_raw):
    fv = CALIBRACION.get('VI_curva', 1.0)
    fi = CALIBRACION.get('I_string_curva', 1.0)
    v_cal = [x / fv for x in v_raw]
    i_cal = [x / fi for x in i_raw]
    return v_cal, i_cal

def suavizar_curva(datos, window=9, polyorder=3):
    n = len(datos)
    if n < 5:
        return datos 

    if _SCIPY_OK:
        w = min(window, n if n % 2 == 1 else n - 1)
        if w < 5:
            return datos
        po = min(polyorder, w - 1)
        try:
            return savgol_filter(datos, window_length=w, polyorder=po).tolist()
        except Exception:
            pass

    arr = np.array(datos, dtype=float)
    k = min(window, n)
    if k < 3:
        return datos
    kernel = np.ones(k) / k
    suavizado = np.convolve(arr, kernel, mode='same')
    return suavizado.tolist()

def procesar_iv_parcial(parts):
    global iv_blocks, iv_total_blocks
    if len(parts) < 7: return
    try:
        blk_idx   = int(parts[3])
        blk_total = int(parts[4])
    except: return

    iv_total_blocks = blk_total
    iv_blocks[blk_idx] = {
        "v": [float(x) for x in parts[5].split(",") if x.strip()],
        "i": [float(x) for x in parts[6].split(",") if x.strip()]
    }

    if len(iv_blocks) == iv_total_blocks:
        global iv_voltages, iv_currents, iv_curvas
        v_raw, i_raw = [], []
        for k in sorted(iv_blocks.keys()):
            v_raw += iv_blocks[k]["v"]
            i_raw += iv_blocks[k]["i"]
        iv_blocks = {}; iv_total_blocks = 0

        # 1. Calibrar: convertir cuentas ADC raw a voltios/amperios reales
        v_cal, i_cal = calibrar_curva_iv(v_raw, i_raw)

        # 2. Suavizar: reduce el ruido del ADC manteniendo la forma de la curva
        v_completo = suavizar_curva(v_cal, window=9, polyorder=3)
        i_completo = suavizar_curva(i_cal, window=9, polyorder=3)

        tipo = iv_tipo_pendiente
        iv_curvas[tipo] = {"v": v_completo, "i": i_completo}

        # Compatibilidad: iv_voltages/iv_currents siempre apuntan a la
        # última curva recibida (para CSV, OP, MPP, etc.)
        iv_voltages = v_completo
        iv_currents = i_completo

        nombre_tipo = IV_COLORES.get(tipo, {"nombre": tipo})["nombre"]
        lbl_iv_puntos.config(text=f"{len(iv_voltages)} puntos ({nombre_tipo})")
        _log_status(f"Curva IV recibida: {nombre_tipo} — {len(v_completo)} puntos "
                    f"(calibrada y suavizada)")
        redibujar_iv(); notebook.select(tab_iv_curve)

# ══════════════════════════════════════════════════════════════
#  FUNCIONES DE PERTURBACIÓN
# ══════════════════════════════════════════════════════════════
def procesar_perturb_tx(parts):
    mac = parts[1] if len(parts) > 1 else "?"
    perturb_resultados[mac] = {"estado": "TX", "magnitud": 0}
    _log_status(f"⚡ PERTURB_TX: {mac} inyectando...")
    actualizar_tabla_perturb()

def procesar_perturb_rx(parts):
    mac      = parts[1] if len(parts) > 1 else "?"
    resultado= parts[3] if len(parts) > 3 else "?"
    magnitud = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0
    perturb_resultados[mac] = {"estado": resultado, "magnitud": magnitud}
    icono = "✅ DETECTADO" if resultado == "SI" else "❌ NO DETECTADO"
    _log_status(f"{icono}: {mac} (magnitud={magnitud})")
    actualizar_tabla_perturb()

def actualizar_tabla_perturb():
    for r in tree_perturb.get_children(): tree_perturb.delete(r)
    for mac, d in perturb_resultados.items():
        pvsx_n = nodes[mac]["pvsx"] if mac in nodes else "?"
        est = d["estado"]
        icono = "⚡ INYECTOR" if est=="TX" else ("✅ DETECTADO" if est=="SI" else "❌ NO DETECTADO")
        tag   = "tx" if est=="TX" else ("si" if est=="SI" else "no")
        tree_perturb.insert("","end", values=(pvsx_n, mac, icono, str(d["magnitud"])), tags=(tag,))

def limpiar_perturb():
    global perturb_resultados
    perturb_resultados = {}
    actualizar_tabla_perturb()

def enviar_perturb():
    mac_tx = entry_perturb_tx.get().strip() or entry_mac.get().strip()
    if not mac_tx:
        messagebox.showwarning("Atención", "Indica la MAC del nodo inyector")
        return
    rx_text  = entry_perturb_rx.get().strip()
    macs_rx  = [m.strip() for m in rx_text.split(",") if m.strip()] if rx_text \
               else [m for m in nodes if m != mac_tx]
    if not macs_rx:
        messagebox.showwarning("Atención", "No hay nodos oyentes.")
        return
    limpiar_perturb()
    _log_status(f"═══ PERTURBACIÓN  Inyector:{mac_tx}  Oyentes:{','.join(macs_rx)} ═══")
    for mac_rx in macs_rx:
        pvsx_rx = nodes[mac_rx]["pvsx"] if mac_rx in nodes else pvsx
        msg = f"{pvsx_rx}//{mac_rx}//PERTURB_LISTEN"
        client.publish(f"{pvsx_rx}/REQUEST", msg)
        _log_status(f"→ PERTURB_LISTEN → {mac_rx}")
    root.after(2000, lambda: _enviar_inyector(mac_tx))

def _enviar_inyector(mac_tx):
    pvsx_tx = nodes[mac_tx]["pvsx"] if mac_tx in nodes else pvsx
    msg = f"{pvsx_tx}//{mac_tx}//PERTURB"
    client.publish(f"{pvsx_tx}/REQUEST", msg)
    _log_status(f"PERTURB → {mac_tx}")

# ══════════════════════════════════════════════════════════════
#  FUNCIONES DE LOCALIZACIÓN
# ══════════════════════════════════════════════════════════════

def rssi_a_distancia(rssi, rssi_1m=-40, n=2.0):
    if rssi >= 0 or rssi <= -110: return None
    try:    return 10 ** ((rssi_1m - rssi) / (10 * n))
    except: return None

def trilateracion(ref_pos, distancias):
    """Mínimos cuadrados con ≥2 referencias."""
    pts = [(ref_pos[m][0], ref_pos[m][1], d)
           for m, d in distancias.items()
           if m in ref_pos and d is not None]
    if len(pts) < 2: return None
    if len(pts) == 2:
        (x1,y1,d1),(x2,y2,d2) = pts[0], pts[1]
        w1,w2 = 1/(d1+.001), 1/(d2+.001)
        return (round((x1*w1+x2*w2)/(w1+w2),1),
                round((y1*w1+y2*w2)/(w1+w2),1))
    x1,y1,d1 = pts[0]
    A,b = [],[]
    for xi,yi,di in pts[1:]:
        A.append([2*(xi-x1), 2*(yi-y1)])
        b.append(di**2 - xi**2 - yi**2 - d1**2 + x1**2 + y1**2)
    try:
        n = len(A)
        AtA=[[sum(A[i][j]*A[i][k] for i in range(n)) for k in range(2)] for j in range(2)]
        Atb=[sum(A[i][j]*b[i] for i in range(n)) for j in range(2)]
        det = AtA[0][0]*AtA[1][1] - AtA[0][1]*AtA[1][0]
        if abs(det) < 1e-10: return None
        x = (AtA[1][1]*Atb[0] - AtA[0][1]*Atb[1]) / det
        y = (AtA[0][0]*Atb[1] - AtA[1][0]*Atb[0]) / det
        return (round(x,1), round(y,1))
    except: return None

def leer_referencias():
    """Lee las filas de la tabla de referencias introducidas por el usuario."""
    refs = []
    for row_e in ref_entries:
        pvsx_r = row_e["pvsx"].get().strip()
        mac_r  = row_e["mac"].get().strip()
        try:   x_r = float(row_e["x"].get())
        except: x_r = None
        try:   y_r = float(row_e["y"].get())
        except: y_r = None
        if pvsx_r or mac_r:
            refs.append({"pvsx": pvsx_r, "mac": mac_r, "x": x_r, "y": y_r})
    return refs

def iniciar_locate_secuencial():
    """Envía LOCATE a cada nodo UNO POR UNO con delay entre ellos."""
    global locate_cola, locate_cola_idx, locate_en_curso
    if not nodes:
        messagebox.showwarning("Atención", "No hay nodos conectados.")
        return
    limpiar_locate()
    locate_cola     = list(nodes.keys())
    locate_cola_idx = 0
    locate_en_curso = True
    total = len(locate_cola)
    _log_status(f"LOCATE secuencial — {total} nodo(s), {LOCATE_DELAY_MS}ms entre cada uno")
    lbl_locate_estado.config(text=f"Midiendo 1/{total}...")
    _enviar_locate_siguiente()

def _enviar_locate_siguiente():
    """Envía LOCATE al siguiente nodo de la cola."""
    global locate_cola_idx, locate_en_curso
    if locate_cola_idx >= len(locate_cola):
        locate_en_curso = False
        lbl_locate_estado.config(text=f"✓ Completado ({len(locate_cola)} nodos)")
        _log_status("LOCATE completado. Calculando posiciones...")
        calcular_posiciones()
        return
    mac    = locate_cola[locate_cola_idx]
    pvsx_n = nodes[mac]["pvsx"] if mac in nodes else pvsx
    msg    = f"{pvsx_n}//{mac}//LOCATE"
    client.publish(f"{pvsx_n}/REQUEST", msg)
    idx_str = f"{locate_cola_idx+1}/{len(locate_cola)}"
    _log_status(f"LOCATE → {pvsx_n} ({mac})  [{idx_str}]")
    lbl_locate_estado.config(text=f"Midiendo {idx_str}...")
    locate_cola_idx += 1
    root.after(LOCATE_DELAY_MS, _enviar_locate_siguiente)

def procesar_locate(parts, payload):
    """Recibe y almacena la tabla RSSI de un nodo.

    Formato real del Arduino (MQTT.ino):
      PVSx // MAC // LOCATE // RSSI_ROUTER:<val> // VECINOS:<mac1@rssi1,...> // MODO:<modo> // STRING:<id>
    """
    if len(parts) < 4: return
    mac_orig  = parts[1]
    pvsx_orig = parts[0]

    tabla = {}

    # Recorrer parts[3..] buscando las secciones clave
    for seg in parts[3:]:
        seg = seg.strip()
        if seg.startswith("RSSI_ROUTER:"):
            try:
                rssi_router = int(seg.split(":", 1)[1])
                tabla["ROUTER"] = rssi_router
            except: pass

        elif seg.startswith("VECINOS:"):
            vecinos_str = seg.split(":", 1)[1]
            if vecinos_str and vecinos_str != "NINGUNO":
                for par in vecinos_str.split(","):
                    par = par.strip()
                    if "@" in par:
                        nombre, rssi_s = par.rsplit("@", 1)
                        try:
                            tabla[nombre.strip()] = int(rssi_s.strip())
                        except: pass

    locate_tablas[mac_orig] = tabla
    _log_status(f"LOCATE recibido de {pvsx_orig} — "
                f"Router:{tabla.get('ROUTER','?')}dBm  {len(tabla)-1} vecinos")

    guardar_archivo_nodo(mac_orig, pvsx_orig, tabla)
    actualizar_tabla_raw()

    if not locate_en_curso or len(locate_tablas) == len(locate_cola):
        calcular_posiciones()

def guardar_archivo_nodo(mac, pvsx_n, tabla):
    """
    Guarda un archivo TXT con las mediciones RSSI del nodo.
    Se crea automáticamente en la carpeta 'locate_data/'.
    """
    try:
        os.makedirs("locate_data", exist_ok=True)
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = mac.replace(":", "")
        path = f"locate_data/{pvsx_n}_{safe}_{ts}.txt"
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"=== MEDICIÓN LOCATE ===\n")
            f.write(f"Nodo PVSx  : {pvsx_n}\n")
            f.write(f"MAC        : {mac}\n")
            f.write(f"Fecha/Hora : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"RSSI_1m    : {entry_rssi_1m.get()} dBm\n")
            f.write(f"Factor_n   : {entry_factor_n.get()}\n\n")
            f.write(f"{'Vecino':<25} {'RSSI (dBm)':>12} {'Distancia est. (m)':>20}\n")
            f.write("-" * 60 + "\n")
            try:
                r1m = float(entry_rssi_1m.get())
                fn  = float(entry_factor_n.get())
            except:
                r1m, fn = -40, 2.0
            for vecino, rssi in sorted(tabla.items()):
                dist = rssi_a_distancia(rssi, r1m, fn)
                dist_str = f"{dist:.2f}" if dist else "N/A"
                f.write(f"{vecino:<25} {rssi:>12} {dist_str:>20}\n")
        _log_status(f"Archivo guardado: {path}")
    except Exception as e:
        _log_status(f"⚠ Error guardando archivo: {e}")

def calcular_posiciones():
    """Trilateración usando las referencias manuales + datos RSSI."""
    global locate_posiciones
    locate_posiciones = {}

    try:
        r1m = float(entry_rssi_1m.get())
        fn  = float(entry_factor_n.get())
    except:
        r1m, fn = -40, 2.0

    # Construir mapa de referencias {mac_o_id: (x, y)}
    refs = leer_referencias()
    ref_pos = {}

    for ref in refs:
        if ref["x"] is None or ref["y"] is None: continue
        # Intentar asociar la referencia a una MAC real de la red
        mac_ref = ref["mac"]
        if not mac_ref:
            # Buscar por PVSx
            for m, d in nodes.items():
                if d["pvsx"] == ref["pvsx"]:
                    mac_ref = m; break
        if mac_ref:
            ref_pos[mac_ref] = (ref["x"], ref["y"])
            locate_posiciones[mac_ref] = {
                "x": ref["x"], "y": ref["y"],
                "pvsx": ref["pvsx"] or (nodes[mac_ref]["pvsx"] if mac_ref in nodes else "?"),
                "rssi_router": locate_tablas.get(mac_ref, {}).get("ROUTER", -100),
                "tipo": "REFERENCIA"
            }

    # Si no hay referencias manuales con MAC, usar ROUTER como referencia
    if not ref_pos and refs and refs[0]["x"] is not None:
        ref_pos["__ROUTER__"] = (refs[0]["x"], refs[0]["y"])

    # Calcular posición de nodos sin referencia asignada
    for mac, tabla in locate_tablas.items():
        if mac in locate_posiciones: continue

        distancias = {}
        # Distancia hacia referencias conocidas
        for mac_ref, pos_ref in ref_pos.items():
            rssi = tabla.get(mac_ref)
            if rssi is None and mac_ref in locate_tablas:
                rssi = locate_tablas[mac_ref].get(mac)
            if rssi is not None:
                d = rssi_a_distancia(rssi, r1m, fn)
                if d: distancias[mac_ref] = d

        # Distancia hacia ROUTER
        if "ROUTER" in tabla and "__ROUTER__" in ref_pos:
            d = rssi_a_distancia(tabla["ROUTER"], r1m, fn)
            if d: distancias["__ROUTER__"] = d
        elif "ROUTER" in tabla and refs and refs[0]["x"] is not None:
            d = rssi_a_distancia(tabla["ROUTER"], r1m, fn)
            if d:
                ref_pos["__ROUTER__"] = (refs[0]["x"], refs[0]["y"])
                distancias["__ROUTER__"] = d

        pos = trilateracion(ref_pos, distancias)
        pvsx_n = nodes[mac]["pvsx"] if mac in nodes else "?"
        locate_posiciones[mac] = {
            "x": pos[0] if pos else None,
            "y": pos[1] if pos else None,
            "pvsx": pvsx_n,
            "rssi_router": tabla.get("ROUTER", -100),
            "tipo": "CALCULADO" if pos else "SIN_DATOS"
        }
        if pos: ref_pos[mac] = pos  # usar como referencia para siguientes

    actualizar_tabla_posiciones()
    dibujar_mapa()

def actualizar_tabla_raw():
    for r in tree_locate_raw.get_children(): tree_locate_raw.delete(r)
    try:
        r1m = float(entry_rssi_1m.get())
        fn  = float(entry_factor_n.get())
    except:
        r1m, fn = -40, 2.0
    for mac_o, tabla in locate_tablas.items():
        pvsx_n = nodes[mac_o]["pvsx"] if mac_o in nodes else "?"
        for vecino, rssi in tabla.items():
            dist = rssi_a_distancia(rssi, r1m, fn)
            tree_locate_raw.insert("","end",
                values=(pvsx_n, mac_o, vecino, rssi,
                        f"{dist:.1f} m" if dist else "?"))

def actualizar_tabla_posiciones():
    for r in tree_locate_pos.get_children(): tree_locate_pos.delete(r)
    for mac, d in locate_posiciones.items():
        x_s = f"{d['x']:.1f} m" if d["x"] is not None else "?"
        y_s = f"{d['y']:.1f} m" if d["y"] is not None else "?"
        tag = "ref" if d["tipo"]=="REFERENCIA" else \
              ("calc" if d["tipo"]=="CALCULADO" else "nop")
        tree_locate_pos.insert("","end",
            values=(d["pvsx"], mac, x_s, y_s, d["rssi_router"], d["tipo"]),
            tags=(tag,))

def dibujar_mapa():
    canvas_mapa.delete("all")
    w = canvas_mapa.winfo_width()  or 600
    h = canvas_mapa.winfo_height() or 350
    if not locate_posiciones:
        canvas_mapa.create_text(w//2, h//2, text="Sin datos",
                                fill="gray", font=("Segoe UI",11))
        return
    xs = [d["x"] for d in locate_posiciones.values() if d["x"] is not None]
    ys = [d["y"] for d in locate_posiciones.values() if d["y"] is not None]
    if not xs: return
    mg = 50
    rx = max(max(xs)-min(xs), 1); ry = max(max(ys)-min(ys), 1)
    def tc(x, y):
        cx = mg + (x-min(xs))/rx*(w-2*mg)
        cy = mg + (y-min(ys))/ry*(h-2*mg)
        return cx, cy
    # Grid
    for i in range(6):
        xi = mg + i*(w-2*mg)//5
        canvas_mapa.create_line(xi,mg,xi,h-mg, fill="#e2e8f0", dash=(2,4))
        canvas_mapa.create_line(mg,mg+i*(h-2*mg)//5,w-mg,mg+i*(h-2*mg)//5,
                                fill="#e2e8f0", dash=(2,4))
    # Líneas entre nodos con RSSI conocido
    macs = list(locate_posiciones.keys())
    for i, m1 in enumerate(macs):
        d1 = locate_posiciones[m1]
        if d1["x"] is None: continue
        for m2 in macs[i+1:]:
            d2 = locate_posiciones[m2]
            if d2["x"] is None: continue
            rssi = locate_tablas.get(m1,{}).get(m2) or locate_tablas.get(m2,{}).get(m1)
            if rssi:
                cx1,cy1 = tc(d1["x"],d1["y"])
                cx2,cy2 = tc(d2["x"],d2["y"])
                canvas_mapa.create_line(cx1,cy1,cx2,cy2, fill="#94a3b8", width=1, dash=(3,3))
                canvas_mapa.create_text((cx1+cx2)/2,(cy1+cy2)/2-8,
                    text=f"{rssi}dBm", fill="#64748b", font=("Segoe UI",7))
    # Nodos
    r = 20
    for mac, d in locate_posiciones.items():
        if d["x"] is None: continue
        cx, cy = tc(d["x"], d["y"])
        color  = "#2b6cb0" if d["tipo"]=="REFERENCIA" else \
                 "#276749" if d["tipo"]=="CALCULADO"  else "#718096"
        canvas_mapa.create_oval(cx-r,cy-r,cx+r,cy+r, fill=color,
                                outline="#1a202c", width=2)
        canvas_mapa.create_text(cx,cy, text=d["pvsx"],
                                fill="white", font=("Segoe UI",8,"bold"))
        canvas_mapa.create_text(cx,cy+r+10,
            text=f"({d['x']},{d['y']})", fill="#4a5568", font=("Segoe UI",7))

def limpiar_locate():
    global locate_tablas, locate_posiciones, locate_cola, locate_cola_idx, locate_en_curso
    locate_tablas = {}; locate_posiciones = {}
    locate_cola = []; locate_cola_idx = 0; locate_en_curso = False
    lbl_locate_estado.config(text="")
    actualizar_tabla_raw(); actualizar_tabla_posiciones()
    canvas_mapa.delete("all")

def exportar_csv():
    if not locate_tablas and not locate_posiciones:
        messagebox.showwarning("Atención", "No hay datos para exportar.")
        return
    path = filedialog.asksaveasfilename(
        defaultextension=".csv",
        filetypes=[("CSV","*.csv"),("Todos","*.*")],
        title="Guardar datos de localización",
        initialfile=f"locate_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
    if not path: return
    try:
        r1m = float(entry_rssi_1m.get()); fn = float(entry_factor_n.get())
    except:
        r1m, fn = -40, 2.0
    try:
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["=== POSICIONES CALCULADAS ==="])
            w.writerow(["PVSx","MAC","X (m)","Y (m)","RSSI_Router","Tipo"])
            for mac, d in locate_posiciones.items():
                w.writerow([d["pvsx"], mac,
                             d["x"] if d["x"] is not None else "N/A",
                             d["y"] if d["y"] is not None else "N/A",
                             d["rssi_router"], d["tipo"]])
            w.writerow([])
            w.writerow(["=== MATRIZ RSSI ==="])
            w.writerow(["Nodo","MAC_Origen","Vecino","RSSI (dBm)","Distancia (m)"])
            for mac_o, tabla in locate_tablas.items():
                pvsx_n = nodes[mac_o]["pvsx"] if mac_o in nodes else "?"
                for vecino, rssi in tabla.items():
                    dist = rssi_a_distancia(rssi, r1m, fn)
                    w.writerow([pvsx_n, mac_o, vecino, rssi,
                                 f"{dist:.2f}" if dist else "N/A"])
            w.writerow([])
            w.writerow(["=== REFERENCIAS USADAS ==="])
            for ref in leer_referencias():
                if ref["pvsx"] or ref["mac"]:
                    w.writerow([ref["pvsx"], ref["mac"], ref["x"], ref["y"]])
            w.writerow([])
            w.writerow(["=== PARÁMETROS ==="])
            w.writerow(["RSSI_1m", entry_rssi_1m.get()])
            w.writerow(["Factor_n", entry_factor_n.get()])
            w.writerow(["Fecha", datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
        messagebox.showinfo("Exportado", f"Guardado en:\n{path}")
        _log_status(f"CSV exportado: {path}")
    except Exception as e:
        messagebox.showerror("Error", str(e))


# ══════════════════════════════════════════════════════════════
#  FUNCIONES DE TOPOLOGÍA
# ══════════════════════════════════════════════════════════════
import json as _json

_last_topo = {}   # último JSON de topología recibido

def procesar_topologia(payload):
    global _last_topo
    try:
        data = _json.loads(payload)
    except Exception:
        _log_status("⚠ Topología: JSON inválido")
        return
    _last_topo = data
    root.after(0, _actualizar_vista_topo)

def _actualizar_vista_topo():
    data = _last_topo
    if not data: return

    ts = datetime.now().strftime('%H:%M:%S')
    lbl_topo_ts.config(text=f"Actualizado: {ts}")

    # ── Resumen gateway ──────────────────────────────────────
    lbl_gw_id.config(  text=data.get("nodo_local", "---"))
    lbl_gw_rssi.config(text=f"{data.get('rssi_local', '?')} dBm")
    lbl_gw_ip.config(  text=data.get("ip_local", "---"))
    lbl_gw_modo.config(text=data.get("modo_local", "---"))
    lbl_gw_nnodos.config(text=str(data.get("total_nodos_malla", "?")))

    _log_status(f"Topología recibida — GW: {data.get('nodo_local','?')} "
                f"RSSI:{data.get('rssi_local','?')}dBm "
                f"Nodos:{data.get('total_nodos_malla','?')}")

    # ── Tabla de nodos ───────────────────────────────────────
    for r in tree_topo.get_children(): tree_topo.delete(r)

    nodos = data.get("nodos_registrados", [])
    for n in nodos:
        inact_ms  = n.get("ms_inactivo", 0)
        inact_str = f"{inact_ms//1000}s" if inact_ms < 120000 else f"{inact_ms//60000}min"
        activo    = n.get("activo", False)
        es_gw     = n.get("es_gateway", False)
        tag = "gw" if es_gw else ("activo" if activo else "inact")
        tree_topo.insert("", "end", values=(
            n.get("nombre","?"),
            n.get("mesh_id","?"),
            f"{n.get('rssi','?')} dBm",
            n.get("modo","?"),
            "✓" if es_gw else "",
            "✓" if activo else "✗",
            inact_str
        ), tags=(tag,))

    # Nodos en malla pero sin beacon
    for n in data.get("nodos_mesh_sin_beacon", []):
        tree_topo.insert("", "end", values=(
            n.get("nombre","?"), n.get("mesh_id","?"),
            "?", "?", "", "?", "Sin beacon"
        ), tags=("inact",))

    # ── Mapa visual ──────────────────────────────────────────
    _dibujar_mapa_topo(data)

def _dibujar_mapa_topo(data):
    canvas_topo.delete("all")
    w = canvas_topo.winfo_width()  or 380
    h = canvas_topo.winfo_height() or 350

    nodos_raw = data.get("nodos_registrados", [])
    gw_nombre = data.get("nodo_local", "GW")
    gw_rssi   = data.get("rssi_local", -100)

    # Construir lista unificada: gateway + nodos
    todos = [{"nombre": gw_nombre, "rssi": gw_rssi,
              "es_gw": True, "activo": True}]
    for n in nodos_raw:
        todos.append({"nombre": n.get("nombre","?"),
                      "rssi":   n.get("rssi", -100),
                      "es_gw":  n.get("es_gateway", False),
                      "activo": n.get("activo", False)})

    if not todos: return

    # Distribuir en círculo; gateway en el centro
    cx, cy = w // 2, h // 2
    radio  = min(w, h) // 2 - 55
    n_nodos = len(todos) - 1  # sin el GW

    posiciones = {}
    # Gateway: centro
    posiciones[gw_nombre] = (cx, cy)

    for i, nd in enumerate([n for n in todos if not n["es_gw"]]):
        ang = 2 * math.pi * i / max(n_nodos, 1) - math.pi / 2
        px  = cx + int(radio * math.cos(ang))
        py  = cy + int(radio * math.sin(ang))
        posiciones[nd["nombre"]] = (px, py)

    # Líneas gateway → nodo
    for nd in todos:
        if nd["es_gw"]: continue
        x1, y1 = posiciones[gw_nombre]
        x2, y2 = posiciones.get(nd["nombre"], (cx, cy))
        rssi_v = nd["rssi"]
        # Color de la línea según RSSI: verde fuerte → rojo
        if rssi_v > -60:   lc = "#4ade80"
        elif rssi_v > -75: lc = "#facc15"
        elif rssi_v > -90: lc = "#fb923c"
        else:              lc = "#f87171"
        canvas_topo.create_line(x1, y1, x2, y2, fill=lc, width=2)
        mx, my = (x1+x2)//2, (y1+y2)//2
        canvas_topo.create_text(mx, my-8, text=f"{rssi_v}dBm",
                                fill="#94a3b8", font=("Segoe UI", 7))

    # Dibujar nodos
    r_node = 22
    for nd in todos:
        px, py = posiciones[nd["nombre"]]
        if nd["es_gw"]:
            color, borde, text_c = "#60a5fa", "#1d4ed8", "white"
            r_node = 28
        elif nd["activo"]:
            color, borde, text_c = "#4ade80", "#166534", "black"
            r_node = 22
        else:
            color, borde, text_c = "#f87171", "#991b1b", "white"
            r_node = 22
        canvas_topo.create_oval(px-r_node, py-r_node, px+r_node, py+r_node,
                                fill=color, outline=borde, width=2)
        # Nombre corto (últimos 4 chars de la MAC o PVSx)
        nombre_c = nd["nombre"][-8:] if len(nd["nombre"]) > 8 else nd["nombre"]
        canvas_topo.create_text(px, py, text=nombre_c,
                                fill=text_c, font=("Segoe UI", 7, "bold"))
        canvas_topo.create_text(px, py+r_node+10,
                                text=f"{nd['rssi']}dBm",
                                fill="#94a3b8", font=("Segoe UI", 7))

# ══════════════════════════════════════════════════════════════
#  FUNCIONES MQTT GENERALES
# ══════════════════════════════════════════════════════════════
def _log_status(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    text_area_empty_status.insert(tk.END, f"[{ts}] {msg}\n")
    text_area_empty_status.yview(tk.END)
    text_log.insert(tk.END, f"[{ts}] {msg}\n")
    text_log.yview(tk.END)

def update_topics():
    global topic_data, topic_config, topic_request, topic_status
    topic_data    = f"{pvsx}/DATA"
    topic_config  = f"{pvsx}/CONFIG"
    topic_request = f"{pvsx}/REQUEST"
    topic_status  = f"{pvsx}/STATUS"
    client.subscribe([
        (topic_data, 0), (topic_status, 0),
        (topic_empty_status, 0), (topic_empty_config, 0),
        ("+/STATUS", 0), ("+/DATA", 0),
        ("solar/malla/topologia", 0),
    ])

def update_pvsx():
    global pvsx
    pvsx = entry_pvsx.get().strip() or "EMPTY"
    update_topics()

def add_or_update_node(pvsx_val, mac, modo_malla="NODO"):
    now = time.time()
    ts  = datetime.now().strftime('%H:%M:%S')
    if mac not in nodes:
        nodes[mac] = {"pvsx": pvsx_val, "last_seen": now, "modo": modo_malla}
        if modo_malla == "GATEWAY":
            tag = 'gateway'
        elif modo_malla == "DIRECTO":
            tag = 'directo'
        else:
            tag = 'online'
        tree.insert("","end", iid=mac, values=(pvsx_val, mac, modo_malla, "● ONLINE", ts),
                    tags=(tag,))
    else:
        nodes[mac]["pvsx"]      = pvsx_val
        nodes[mac]["last_seen"] = now
        nodes[mac]["modo"]      = modo_malla
        if modo_malla == "GATEWAY":
            tag = 'gateway'
        elif modo_malla == "DIRECTO":
            tag = 'directo'
        else:
            tag = 'online'
        tree.item(mac, values=(pvsx_val, mac, modo_malla, "● ONLINE", ts), tags=(tag,))

def limpiar_desconectados():
    for mac in list(nodes.keys()):
        try:
            estado = tree.item(mac, 'values')[3]
            if "OFFLINE" in estado:
                tree.delete(mac); del nodes[mac]
        except: pass

def cleanup_nodes():
    now = time.time()
    for mac in list(nodes.keys()):
        if now - nodes[mac]["last_seen"] > NODE_TIMEOUT_SECONDS:
            try:
                v = list(tree.item(mac, 'values'))
                if len(v) >= 4: v[3] = "● OFFLINE"
                tree.item(mac, values=v, tags=('offline',))
            except: pass
    root.after(10000, cleanup_nodes)

def on_connect(client, userdata, flags, rc, properties=None):
    root.after(0, lambda: status_indicator.config(
        text="● Conectado", fg=COLORS['success']))
    update_topics()
    _log_status("✅ Conectado al broker MQTT")

def on_disconnect(client, userdata, rc, properties=None, reasonCode=None):
    root.after(0, lambda: status_indicator.config(
        text="● Desconectado", fg=COLORS['danger']))

def on_message(client_ref, userdata, message):
    topic   = message.topic
    try:    payload = message.payload.decode().strip()
    except: return

    is_heartbeat = "//HB" in payload

    if is_heartbeat:
        text_log.insert(tk.END,
            f"[{datetime.now().strftime('%H:%M:%S')}] {topic}: {payload[:80]} [HB]\n")
        text_log.yview(tk.END)
    else:
        text_log.insert(tk.END,
            f"[{datetime.now().strftime('%H:%M:%S')}] {topic}: {payload[:80]}\n")
        text_log.yview(tk.END)

    if topic.endswith("/STATUS"):
        parts = payload.split("//")
        if len(parts) >= 2:
            pvsx_v, mac = parts[0], parts[1]
            # CORRECCIÓN: Extraer modo de malla si está presente
            modo_malla = "NODO"
            if len(parts) >= 5 and parts[3] == "MESH_HB":
                # Formato: PVSx//MAC//HB//MESH_HB//MODOMALLA
                modo_malla = parts[4] if len(parts) > 4 else "NODO"
            elif len(parts) >= 4 and parts[2] == "HB":
                # Formato: PVSx//MAC//HB//MODOMALLA (directo)
                if len(parts) > 3 and parts[3] in ["DIRECTO", "GATEWAY", "NODO"]:
                    modo_malla = parts[3]

            # Siempre actualizamos el nodo (heartbeat o no) → mantiene ONLINE
            add_or_update_node(pvsx_v, mac, modo_malla)

            if not is_heartbeat:
                label_node_info.config(text=f"Nodo: {pvsx_v}  MAC:{mac}")

        if topic == topic_empty_status:
            if not is_heartbeat:
                text_area_empty_status.insert(tk.END,
                    f"[{datetime.now().strftime('%H:%M:%S')}] {payload}\n")
                text_area_empty_status.yview(tk.END)
                if len(parts) >= 2:
                    entry_pvsx.delete(0,tk.END); entry_pvsx.insert(0,parts[0])
                    entry_mac.delete(0,tk.END);  entry_mac.insert(0,parts[1])
                    update_pvsx()
        else:
            if is_heartbeat:
                if len(parts) >= 2:
                    _log_status(f"Heartbeat recibido: {parts[0]} // {parts[1]}")
                else: 
                    _log_status(f"Heartbeat recibido: {payload}")
            else:
                text_area_status.insert(tk.END,
                    f"[{datetime.now().strftime('%H:%M:%S')}] {payload}\n")
                text_area_status.yview(tk.END)

    elif topic == "solar/malla/topologia":
        # JSON de topología publicado por el gateway
        procesar_topologia(payload)

    elif topic.endswith("/DATA"):
        parts = payload.split("//")
        if len(parts) >= 3:
            cmd = parts[2]
            if cmd == "OP" and len(parts) >= 7:
                try:
                    V_raw, V23_raw, V13_raw, I_raw = (float(parts[3]), float(parts[4]),
                                                        float(parts[5]), float(parts[6]))
                    V   = V_raw   / CALIBRACION['V_MODULE']
                    V23 = V23_raw / CALIBRACION['V23_MOD']
                    V13 = V13_raw / CALIBRACION['V13_MOD']
                    I   = I_raw   / CALIBRACION['I_string']
                    payload_calibrado = (f"{parts[0]}//{parts[1]}//OP//"
                                          f"{V:.2f}//{V23:.2f}//{V13:.2f}//{I:.3f}")
                    text_area_data.insert(tk.END,
                        f"[{datetime.now().strftime('%H:%M:%S')}] {payload_calibrado}\n")
                except (ValueError, ZeroDivisionError):
                    text_area_data.insert(tk.END,
                        f"[{datetime.now().strftime('%H:%M:%S')}] {payload[:120]}\n")
            else:
                text_area_data.insert(tk.END,
                    f"[{datetime.now().strftime('%H:%M:%S')}] {payload[:120]}\n")
            text_area_data.yview(tk.END)

            if   cmd == "IV":           procesar_iv(payload)
            elif cmd == "OP":           procesar_op(payload)
            elif cmd == "MPP":          procesar_mpp(payload)
            elif cmd == "IVP":          procesar_iv_parcial(parts)
            elif cmd == "PERTURB_TX":   procesar_perturb_tx(parts)
            elif cmd == "PERTURB_RX":   procesar_perturb_rx(parts)
            elif cmd == "LOCATE":       procesar_locate(parts, payload)
        else:
            text_area_data.insert(tk.END,
                f"[{datetime.now().strftime('%H:%M:%S')}] {payload[:120]}\n")
            text_area_data.yview(tk.END)

def publish_empty_config():
    msg = entry_empty_config.get().strip()
    if not msg: return
    client.publish(topic_empty_config, msg)
    text_area_empty_config.insert(tk.END,
        f"[{datetime.now().strftime('%H:%M:%S')}] → {topic_empty_config}: {msg}\n")
    text_area_empty_config.yview(tk.END)
    entry_empty_config.delete(0,tk.END)

def publish_pvsx_config():
    msg = entry_pvsx_config.get().strip()
    if not msg: return
    mac = entry_mac.get().strip()
    if not mac:
        text_area_pvsx_config.insert(tk.END,
            f"[{datetime.now().strftime('%H:%M:%S')}] ERROR: MAC vacía\n"); return
    full = msg if "//" in msg else f"{pvsx}//{mac}//{msg}"
    client.publish(topic_config, full)
    text_area_pvsx_config.insert(tk.END,
        f"[{datetime.now().strftime('%H:%M:%S')}] → {topic_config}: {full}\n")
    text_area_pvsx_config.yview(tk.END)
    entry_pvsx_config.delete(0,tk.END)
    if msg.endswith("Reset"):
        root.after(3000, lambda: (
            entry_pvsx.delete(0,tk.END), entry_pvsx.insert(0,"EMPTY"),
            entry_mac.delete(0,tk.END), update_topics()))

def publish_pvsx_request():
    global iv_tipo_pendiente
    msg = entry_pvsx_request.get().strip()
    if not msg: return
    mac = entry_mac.get().strip()
    if not mac:
        text_area_pvsx_request.insert(tk.END,
            f"[{datetime.now().strftime('%H:%M:%S')}] ERROR: MAC vacía\n"); return
    full = msg if "//" in msg else f"{pvsx}//{mac}//{msg}"

    # Recordar qué variante de IV se pidió, ya que la respuesta IVP no
    # incluye el tipo en el payload — lo inferimos de la solicitud enviada.
    cmd_final = full.split("//")[-1].upper()
    if cmd_final == "IV":
        iv_tipo_pendiente = "MO"
    elif cmd_final == "IV23":
        iv_tipo_pendiente = "MO23"
    elif cmd_final == "IV13":
        iv_tipo_pendiente = "MO13"

    client.publish(topic_request, full)
    text_area_pvsx_request.insert(tk.END,
        f"[{datetime.now().strftime('%H:%M:%S')}] → {topic_request}: {full}\n")
    text_area_pvsx_request.yview(tk.END)
    entry_pvsx_request.delete(0,tk.END)

# ══════════════════════════════════════════════════════════════
#  INICIALIZACIÓN
# ══════════════════════════════════════════════════════════════
client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
client.username_pw_set(USERNAME, PASSWORD)
client.tls_set()
client.on_connect    = on_connect
client.on_disconnect = on_disconnect
client.on_message    = on_message

try:
    client.connect(BROKER, PORT)
    client.loop_start()
except Exception as e:
    text_area_empty_status.insert(tk.END, f"ERROR MQTT: {e}\n")

cleanup_nodes()
root.mainloop()
client.loop_stop()
client.disconnect()
