import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
import sqlite3
import os
import sys
from datetime import datetime, timedelta, date
import threading
import time
import ctypes 
import subprocess 

# --- CORREÇÃO PARA CONSOLE ---
if sys.platform == "win32":
    class NullWriter:
        def write(self, text): pass
        def flush(self): pass
        def isatty(self): return False
    if sys.stderr is None: sys.stderr = NullWriter()
    if sys.stdout is None: sys.stdout = NullWriter()

# --- IMPORTAÇÕES DO REPORTLAB (PDF) ---
try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.pdfgen import canvas
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

# --- CONFIGURAÇÃO DE CAMINHOS ---
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

# --- CONFIGURAÇÃO DE TEMAS ---
THEMES = {
    "light": {
        "bg": "#f4f6f7", "header_bg": "#2c3e50", "text": "#34495e",
        "card_bg": "#ffffff", "tree_bg": "#ffffff", "tree_fg": "#34495e",
        "tree_row_alt": "#f7f9f9", "input_bg": "#ffffff", "input_fg": "#000000",
        "row_crit": "#fadbd8" # Apenas vermelho
    },
    "dark": {
        "bg": "#2c3e50", "header_bg": "#1a252f", "text": "#ecf0f1",
        "card_bg": "#34495e", "tree_bg": "#34495e", "tree_fg": "#ecf0f1",
        "tree_row_alt": "#2c3e50", "input_bg": "#7f8c8d", "input_fg": "#ffffff",
        "row_crit": "#641e16" # Apenas vermelho escuro
    }
}

# --- Importação Segura do Pystray ---
TRAY_AVAILABLE = False
try:
    from pystray import Icon as TrayIcon, Menu, MenuItem
    from PIL import Image, ImageTk, ImageDraw
    TRAY_AVAILABLE = True
except ImportError:
    pass

DB_PATH = os.path.join(os.path.expanduser("~"), "pharmastock.db")

# Fontes UI
FONTE_PADRAO = ("Segoe UI", 10)
FONTE_TITULO = ("Segoe UI", 12, "bold")
FONTE_CABECALHO = ("Segoe UI", 18, "bold")

class App:
    def __init__(self, root):
        self.root = root
        self.db_name = DB_PATH
        self.db_conn = None
        self.db_cursor = None
        
        self.tray_icon = None
        self.tray_image_ref = None
        self.tray_active = False
        
        # ID FIXO - Não muda mais com versões
        self.app_id = 'PharmaStock.App.Main' 
        self.current_theme = "light"

        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(self.app_id)
        except Exception:
            pass 

        self.root.title("PharmaStock")
        self.root.geometry("1200x780")

        # Ícones
        try:
            self.icon_path_ico = resource_path("cardiogram.ico")
            self.icon_path_png = resource_path("cardiogram.png")
            
            if os.path.exists(self.icon_path_ico):
                self.root.iconbitmap(self.icon_path_ico)
            
            if os.path.exists(self.icon_path_png):
                self.icon_img = ImageTk.PhotoImage(Image.open(self.icon_path_png))
                self.root.iconphoto(True, self.icon_img)
        except Exception:
            pass

        self._init_db()
        self._setup_ui()
        self.aplicar_tema("light")
        
        self.atualizar_combo_pacientes_cadastro()
        self.atualizar_combo_filtro()
        self.atualizar_lista_remedios()

        self.iniciar_verificador_notificacoes()
        self.iniciar_loop_verificacao_diaria()

        if TRAY_AVAILABLE:
            self._init_tray_icon()
        
        self.root.protocol("WM_DELETE_WINDOW", self.ao_fechar_janela)

        if "--minimized" in sys.argv and self.tray_active:
            self.esconder_janela()

    # --- FORMATADORES INTELIGENTES ---
    def _formatar_dias_extenso(self, dias_str):
        if not dias_str: return "Nenhum"
        dias_lista = [int(d) for d in dias_str.split(',') if d]
        if len(dias_lista) == 7:
            return "Todos os dias"
        mapa = {0: "Seg", 1: "Ter", 2: "Qua", 3: "Qui", 4: "Sex", 5: "Sáb", 6: "Dom"}
        try:
            idxs = sorted(dias_lista)
            nomes = [mapa[i] for i in idxs]
            return ", ".join(nomes)
        except:
            return "Erro"

    def _formatar_qtd_smart(self, valor, unidade_raw):
        u = unidade_raw.lower().strip()
        try:
            val = int(valor)
        except:
            val = 0
        
        if u == "comprimido":
            unidade_fmt = "cp" if val == 1 else "cps"
        elif u == "ml":
            unidade_fmt = "ml"
        elif u == "unidade":
            unidade_fmt = "unid." if val == 1 else "unids."
        else:
            unidade_fmt = u if val == 1 else u + "s"
            
        return f"{val} {unidade_fmt}"

    # --- PDF HEADER/FOOTER ---
    def _draw_pdf_header_footer(self, canvas, doc):
        canvas.saveState()
        primary_color = colors.HexColor("#2c3e50")
        accent_color = colors.HexColor("#3498db")
        
        canvas.setFillColor(primary_color)
        canvas.rect(0, A4[1] - 3*cm, A4[0], 3*cm, fill=1, stroke=0)
        canvas.setFillColor(accent_color)
        canvas.rect(0, A4[1] - 3.1*cm, A4[0], 0.1*cm, fill=1, stroke=0)

        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 24)
        canvas.drawString(2*cm, A4[1] - 1.8*cm, "PharmaStock")
        canvas.setFont("Helvetica", 12)
        canvas.drawString(2*cm, A4[1] - 2.4*cm, "Gestão Inteligente de Medicamentos")

        data_hoje = datetime.now().strftime("%d/%m/%Y")
        canvas.setFont("Helvetica-Bold", 12)
        canvas.drawRightString(A4[0] - 2*cm, A4[1] - 1.8*cm, "RELATÓRIO DE ESTOQUE")
        canvas.setFont("Helvetica", 10)
        canvas.drawRightString(A4[0] - 2*cm, A4[1] - 2.4*cm, f"Gerado em: {data_hoje}")

        canvas.setStrokeColor(colors.lightgrey)
        canvas.line(2*cm, 2*cm, A4[0]-2*cm, 2*cm)
        canvas.setFont("Helvetica", 9)
        canvas.setFillColor(colors.grey)
        canvas.drawString(2*cm, 1.5*cm, "PharmaStock Pro - Controle Pessoal")
        page_num = canvas.getPageNumber()
        canvas.drawRightString(A4[0] - 2*cm, 1.5*cm, f"Página {page_num}")
        canvas.restoreState()

    # --- GERADOR DE PDF ---
    def gerar_pdf_paciente(self):
        if not PDF_AVAILABLE:
            messagebox.showerror("Erro", "Biblioteca 'reportlab' não encontrada.")
            return

        paciente_nome = self.combo_filtro.get()
        if not paciente_nome or paciente_nome == "Todos":
            pacientes = [p[0] for p in self.db_cursor.execute("SELECT nome FROM pacientes").fetchall()]
            if not pacientes:
                messagebox.showwarning("Aviso", "Sem pacientes cadastrados.")
                return
            escolha = simpledialog.askstring("PDF", "Digite o nome do paciente:")
            if not escolha or escolha not in pacientes: return
            paciente_nome = escolha

        try:
            query = """
                SELECT r.nome, r.doses_por_dia, r.estoque_atual, r.unidade, r.dias_semana
                FROM remedios r
                JOIN pacientes p ON r.paciente_id = p.id
                WHERE p.nome = ? ORDER BY r.nome
            """
            dados = self.db_cursor.execute(query, (paciente_nome,)).fetchall()
            
            if not dados:
                messagebox.showinfo("PDF", "Este paciente não possui medicamentos.")
                return

            arquivo = filedialog.asksaveasfilename(
                defaultextension=".pdf",
                filetypes=[("PDF", "*.pdf")],
                initialfile=f"Relatorio_{paciente_nome}_{date.today().strftime('%d%m%Y')}.pdf"
            )
            if not arquivo: return

            doc = SimpleDocTemplate(arquivo, pagesize=A4, 
                                    rightMargin=1.5*cm, leftMargin=1.5*cm, 
                                    topMargin=4*cm, bottomMargin=3*cm)
            elements = []
            styles = getSampleStyleSheet()

            style_nome = ParagraphStyle('NomePac', parent=styles['Normal'], fontSize=16, textColor=colors.HexColor("#2c3e50"), spaceAfter=6, fontName='Helvetica-Bold')
            style_sub = ParagraphStyle('Sub', parent=styles['Normal'], fontSize=10, textColor=colors.grey, spaceAfter=20)
            
            style_cell = ParagraphStyle('CellText', parent=styles['Normal'], fontSize=9, textColor=colors.black, leading=11)
            
            style_cell_red = ParagraphStyle('CellTextRed', parent=styles['Normal'], fontSize=9, textColor=colors.red, leading=11, fontName='Helvetica-Bold')
            style_cell_orange = ParagraphStyle('CellTextOrange', parent=styles['Normal'], fontSize=9, textColor=colors.orange, leading=11, fontName='Helvetica-Bold')
            style_cell_green = ParagraphStyle('CellTextGreen', parent=styles['Normal'], fontSize=9, textColor=colors.green, leading=11, fontName='Helvetica-Bold')

            elements.append(Paragraph(f"Paciente: {paciente_nome}", style_nome))
            elements.append(Paragraph(f"Lista completa de medicamentos, dias de uso e previsões.", style_sub))

            headers = ['Medicamento', 'Dose', 'Estoque', 'Dias de Uso', 'Fim Previsto', 'Status']
            table_data = [headers]
            
            for nome, dose, estoque, unid, dias_str in dados:
                dias_restantes, data_fim = self.calcular_previsao_inteligente(estoque, dose, dias_str)
                dias_formatados = self._formatar_dias_extenso(dias_str)
                
                if (dias_restantes <= 5 and estoque > 0) or estoque == 0:
                    status_text = "CRÍTICO"
                    status_style = style_cell_red
                elif dias_restantes <= 15:
                    status_text = "ATENÇÃO"
                    status_style = style_cell_orange
                else:
                    status_text = "OK"
                    status_style = style_cell_green

                dose_display = self._formatar_qtd_smart(dose, unid)
                estoque_display = self._formatar_qtd_smart(estoque, unid)

                linha = [
                    Paragraph(nome, style_cell),
                    dose_display,
                    estoque_display,
                    Paragraph(dias_formatados, style_cell),
                    data_fim,
                    Paragraph(status_text, status_style)
                ]
                table_data.append(linha)

            col_widths = [5*cm, 2*cm, 2*cm, 4.5*cm, 2.5*cm, 2*cm]
            t = Table(table_data, colWidths=col_widths)

            table_style = [
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#34495e")),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('ALIGN', (0, 0), (0, -1), 'LEFT'), 
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 9), 
                ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
                ('TOPPADDING', (0, 0), (-1, 0), 10),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#ecf0f1")]),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]

            t.setStyle(TableStyle(table_style))
            elements.append(t)

            elements.append(Spacer(1, 1*cm))
            aviso_style = ParagraphStyle('Aviso', parent=styles['Normal'], fontSize=8, textColor=colors.grey, alignment=1)
            elements.append(Paragraph("Documento para controle de estoque pessoal.", aviso_style))

            doc.build(elements, onFirstPage=self._draw_pdf_header_footer, onLaterPages=self._draw_pdf_header_footer)
            
            messagebox.showinfo("Sucesso", f"PDF Gerado!\nSalvo em: {arquivo}")
            try: os.startfile(arquivo)
            except: pass

        except Exception as e:
            messagebox.showerror("Erro PDF", f"Falha ao gerar: {e}")

    # --- LÓGICA DE TEMAS (UI) ---
    def alternar_tema(self):
        novo_tema = "dark" if self.current_theme == "light" else "light"
        self.aplicar_tema(novo_tema)

    def aplicar_tema(self, tema_nome):
        self.current_theme = tema_nome
        cores = THEMES[tema_nome]
        
        self.root.configure(bg=cores["bg"])
        self.header_frame.configure(bg=cores["header_bg"])
        self.lbl_logo.configure(bg=cores["header_bg"], fg="#ffffff")
        icon_tema = "🌙" if tema_nome == "light" else "☀️"
        self.btn_tema.configure(text=icon_tema)

        style = ttk.Style()
        style.theme_use('clam')
        style.configure(".", background=cores["bg"], foreground=cores["text"], fieldbackground=cores["input_bg"])
        style.configure("TFrame", background=cores["bg"])
        style.configure("TLabel", background=cores["bg"], foreground=cores["text"])
        style.configure("Card.TFrame", background=cores["card_bg"], relief="flat")
        style.configure("White.TLabel", background=cores["card_bg"], foreground=cores["text"])
        style.configure("TEntry", fieldbackground=cores["input_bg"], foreground=cores["input_fg"])
        style.configure("TCombobox", fieldbackground=cores["input_bg"], foreground=cores["input_fg"], background=cores["bg"])
        
        style.configure("TNotebook", background=cores["bg"], borderwidth=0)
        style.configure("TNotebook.Tab", background=cores["bg"], foreground=cores["text"])
        style.map("TNotebook.Tab", 
                  background=[("selected", cores["card_bg"]), ("!selected", cores["header_bg"])],
                  foreground=[("selected", "#3498db"), ("!selected", "#bdc3c7")])

        style.configure("Treeview", background=cores["tree_bg"], fieldbackground=cores["tree_bg"], foreground=cores["tree_fg"], rowheight=30, borderwidth=0)
        style.configure("Treeview.Heading", background=cores["header_bg"], foreground="#ffffff", font=("Segoe UI", 9, "bold"))
        
        # --- CONFIGURAÇÃO DAS TAGS DE COR (LIMPA PARA UI) ---
        self.tree.tag_configure('zebra', background=cores["tree_row_alt"])
        self.tree.tag_configure('critico', foreground="#e74c3c", background=cores["row_crit"]) # Apenas Vermelho na UI
        
        self.atualizar_lista_remedios()

    # --- UI ---
    def _setup_ui(self):
        self.header_frame = tk.Frame(self.root, height=60)
        self.header_frame.pack(fill="x", side="top")
        self.header_frame.pack_propagate(False)

        self.lbl_logo = tk.Label(self.header_frame, text=" 💊 PharmaStock", font=FONTE_CABECALHO)
        self.lbl_logo.pack(side="left", padx=20, pady=10)

        self.btn_tema = tk.Button(self.header_frame, text="🌙", font=("Segoe UI", 12), bd=0, cursor="hand2", command=self.alternar_tema, bg="#34495e", fg="white")
        self.btn_tema.pack(side="right", padx=20, pady=10)

        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=20, pady=20)

        self.tab_dashboard = ttk.Frame(notebook)
        notebook.add(self.tab_dashboard, text="  📊 Visão Geral  ")

        self.tab_cadastro = ttk.Frame(notebook)
        notebook.add(self.tab_cadastro, text="  ➕ Novo Cadastro  ")

        self._setup_tab_dashboard()
        self._setup_tab_cadastro()

    def _setup_tab_dashboard(self):
        top_bar = ttk.Frame(self.tab_dashboard)
        top_bar.pack(fill="x", pady=15)

        ttk.Label(top_bar, text="Filtrar por Paciente:", font=("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 10))
        self.combo_filtro = ttk.Combobox(top_bar, state="readonly", width=25)
        self.combo_filtro.pack(side="left")
        self.combo_filtro.bind("<<ComboboxSelected>>", self.evento_filtro_mudou)

        ttk.Button(top_bar, text="🔄 Atualizar", command=self.atualizar_lista_remedios).pack(side="right")
        ttk.Button(top_bar, text="📄 Gerar PDF", command=self.gerar_pdf_paciente).pack(side="right", padx=10)
        ttk.Button(top_bar, text="🔔 Testar Alerta", command=self.testar_notificacao_agora).pack(side="right", padx=10)

        list_container = ttk.Frame(self.tab_dashboard)
        list_container.pack(fill="both", expand=True)

        colunas = ("remedio", "dose", "estoque", "dias_uso", "dias_rest", "previsao")
        self.tree = ttk.Treeview(list_container, columns=colunas, show="headings", selectmode="browse")
        
        self.tree.heading("remedio", text="Medicamento")
        self.tree.heading("dose", text="Dose Diária")
        self.tree.heading("estoque", text="Estoque Atual")
        self.tree.heading("dias_uso", text="Dias de Uso") 
        self.tree.heading("dias_rest", text="Duração")
        self.tree.heading("previsao", text="Término")

        self.tree.column("remedio", width=250)
        self.tree.column("dose", width=100, anchor="center")
        self.tree.column("estoque", width=100, anchor="center")
        self.tree.column("dias_uso", width=200, anchor="center") 
        self.tree.column("dias_rest", width=100, anchor="center")
        self.tree.column("previsao", width=120, anchor="center")

        scrollbar = ttk.Scrollbar(list_container, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)

        bottom_bar = ttk.Frame(self.tab_dashboard)
        bottom_bar.pack(fill="x", pady=20)

        ttk.Button(bottom_bar, text="➕ Adicionar Estoque", style="Accent.TButton", command=self.adicionar_estoque).pack(side="left", padx=(0, 10))
        ttk.Button(bottom_bar, text="✏️ Corrigir Manualmente", command=self.modificar_estoque).pack(side="left", padx=10)
        ttk.Button(bottom_bar, text="📋 Ver Detalhes", command=self.ver_detalhes).pack(side="left", padx=10)
        ttk.Button(bottom_bar, text="🗑️ Remover", style="Danger.TButton", command=self.remover_remedio).pack(side="right")

    def _setup_tab_cadastro(self):
        center_frame = ttk.Frame(self.tab_cadastro)
        center_frame.pack(expand=True)
        card = ttk.LabelFrame(center_frame, text=" Preencha os dados ", padding=30, style="Card.TFrame")
        card.pack(fill="both", padx=20, pady=20)

        ttk.Label(card, text="Paciente:", style="White.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 5))
        frame_pac = ttk.Frame(card, style="Card.TFrame")
        frame_pac.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 20))
        self.combo_paciente_cadastro = ttk.Combobox(frame_pac, state="readonly", width=35, font=("Segoe UI", 11))
        self.combo_paciente_cadastro.pack(side="left", fill="x", expand=True)
        ttk.Button(frame_pac, text="+", width=4, command=self.adicionar_paciente_dialog).pack(side="left", padx=(10, 0))

        ttk.Label(card, text="Nome do Medicamento:", style="White.TLabel").grid(row=2, column=0, sticky="w", pady=(0, 5))
        self.entry_nome = ttk.Entry(card, width=40, font=("Segoe UI", 11))
        self.entry_nome.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 20))

        frame_nums = ttk.Frame(card, style="Card.TFrame")
        frame_nums.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(0, 20))

        col_dose = ttk.Frame(frame_nums, style="Card.TFrame")
        col_dose.pack(side="left", fill="x", expand=True, padx=(0, 10))
        ttk.Label(col_dose, text="Dose Diária:", style="White.TLabel").pack(anchor="w")
        self.entry_doses = ttk.Entry(col_dose, font=("Segoe UI", 11))
        self.entry_doses.pack(fill="x")

        col_est = ttk.Frame(frame_nums, style="Card.TFrame")
        col_est.pack(side="left", fill="x", expand=True, padx=(10, 0))
        ttk.Label(col_est, text="Estoque Inicial:", style="White.TLabel").pack(anchor="w")
        self.entry_estoque = ttk.Entry(col_est, font=("Segoe UI", 11))
        self.entry_estoque.pack(fill="x")

        ttk.Label(card, text="Tipo de Unidade:", style="White.TLabel").grid(row=6, column=0, sticky="w", pady=(0, 5))
        frame_radio = ttk.Frame(card, style="Card.TFrame")
        frame_radio.grid(row=7, column=0, columnspan=2, sticky="w", pady=(0, 20))
        
        self.unidade_var = tk.StringVar(value="comprimido")
        ttk.Radiobutton(frame_radio, text="Comprimido", variable=self.unidade_var, value="comprimido").pack(side="left", padx=(0, 15))
        ttk.Radiobutton(frame_radio, text="ML", variable=self.unidade_var, value="ml").pack(side="left", padx=15)
        ttk.Radiobutton(frame_radio, text="Unidade Genérica", variable=self.unidade_var, value="unidade").pack(side="left", padx=15)

        ttk.Label(card, text="Dias de Uso:", style="White.TLabel").grid(row=8, column=0, sticky="w", pady=(0, 5))
        dias_frame = ttk.Frame(card, style="Card.TFrame")
        dias_frame.grid(row=9, column=0, columnspan=2, sticky="w", pady=(0, 30))

        self.vars_dias = []
        dias_nomes = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
        for i, nome in enumerate(dias_nomes):
            var = tk.BooleanVar(value=True)
            chk = tk.Checkbutton(dias_frame, text=nome, variable=var, font=("Segoe UI", 10))
            chk.config(bg="white", activebackground="white")
            r, c = (0, i) if i < 4 else (1, i-4)
            chk.grid(row=r, column=c, sticky="w", padx=(0, 15), pady=2)
            self.vars_dias.append(var)
        ttk.Button(card, text="💾 SALVAR NOVO MEDICAMENTO", style="Accent.TButton", command=self.cadastrar_remedio).grid(row=10, column=0, columnspan=2, sticky="ew", ipady=5)

    # --- LÓGICA DE TRAY E NOTIFICAÇÕES ---
    def _criar_icone_emergencia(self):
        img = Image.new('RGB', (64, 64), color=(52, 152, 219))
        d = ImageDraw.Draw(img)
        d.rectangle((20, 20, 44, 44), fill=(255, 255, 255))
        return img

    def _init_tray_icon(self):
        try:
            path_png = resource_path("cardiogram.png")
            path_ico = resource_path("cardiogram.ico")
            image = None
            if os.path.exists(path_png): image = Image.open(path_png)
            elif os.path.exists(path_ico): image = Image.open(path_ico)
            else: image = self._criar_icone_emergencia()
            menu = Menu(MenuItem('Abrir', self.mostrar_janela_tray, default=True), MenuItem('Sair', self.sair_app_tray))
            self.tray_icon = TrayIcon("PharmaStock", image, "PharmaStock", menu)
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
            self.tray_active = True
        except Exception: self.tray_active = False

    def ao_fechar_janela(self):
        if self.tray_active: self.root.withdraw()
        else: self.sair_app()

    def enviar_notificacao_limpa(self, titulo, mensagem):
        try:
            ps_script = f"""
            $ErrorActionPreference = 'SilentlyContinue'
            [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] > $null
            $template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
            $textNodes = $template.GetElementsByTagName("text")
            $textNodes.Item(0).AppendChild($template.CreateTextNode("{titulo}")) > $null
            $textNodes.Item(1).AppendChild($template.CreateTextNode("{mensagem}")) > $null
            $toast = [Windows.UI.Notifications.ToastNotification]::new($template)
            $notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("{self.app_id}")
            $notifier.Show($toast)
            """
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            subprocess.Popen(["powershell", "-Command", ps_script], startupinfo=startupinfo)
        except Exception: pass

    # --- BANCO DE DADOS ---
    def _init_db(self):
        try:
            self.db_conn = sqlite3.connect(self.db_name, check_same_thread=False)
            self.db_cursor = self.db_conn.cursor()
            self.db_cursor.execute("PRAGMA foreign_keys = ON;")
            self.db_cursor.execute("CREATE TABLE IF NOT EXISTS pacientes (id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL UNIQUE)")
            self.db_cursor.execute("SELECT count(*) FROM pacientes")
            if self.db_cursor.fetchone()[0] == 0: self.db_cursor.execute("INSERT INTO pacientes (nome) VALUES ('Principal')")
            self.db_cursor.execute("CREATE TABLE IF NOT EXISTS remedios (id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL, doses_por_dia INTEGER NOT NULL, estoque_atual INTEGER NOT NULL DEFAULT 0, unidade TEXT NOT NULL DEFAULT 'comprimido', paciente_id INTEGER, dias_semana TEXT DEFAULT '0,1,2,3,4,5,6', FOREIGN KEY(paciente_id) REFERENCES pacientes(id) ON DELETE CASCADE)")
            self.db_cursor.execute("CREATE TABLE IF NOT EXISTS app_info (id INTEGER PRIMARY KEY, last_run_date TEXT NOT NULL)")
            self.db_conn.commit()
            self._atualizar_estoque_automatico()
        except sqlite3.Error as e:
            messagebox.showerror("Erro BD", f"Erro fatal: {e}")
            self.root.quit()

    def _atualizar_estoque_automatico(self):
        try:
            hoje = date.today()
            self.db_cursor.execute("SELECT last_run_date FROM app_info WHERE id = 1")
            resultado = self.db_cursor.fetchone()
            if not resultado:
                self.db_cursor.execute("INSERT INTO app_info (id, last_run_date) VALUES (1, ?)", (hoje.strftime('%Y-%m-%d'),))
                self.db_conn.commit()
                return False
            last_run = datetime.strptime(resultado[0], '%Y-%m-%d').date()
            if last_run >= hoje: return False
            remedios = self.db_cursor.execute("SELECT id, doses_por_dia, estoque_atual, dias_semana FROM remedios").fetchall()
            for rem_id, doses, estoque, dias_str in remedios:
                if estoque <= 0: continue
                dias_ativos = [int(d) for d in dias_str.split(',') if d]
                consumo = 0
                temp_date = last_run + timedelta(days=1)
                while temp_date <= hoje:
                    if temp_date.weekday() in dias_ativos: consumo += doses
                    temp_date += timedelta(days=1)
                if consumo > 0:
                    novo = max(0, estoque - consumo)
                    self.db_cursor.execute("UPDATE remedios SET estoque_atual = ? WHERE id = ?", (novo, rem_id))
            self.db_cursor.execute("UPDATE app_info SET last_run_date = ? WHERE id = 1", (hoje.strftime('%Y-%m-%d'),))
            self.db_conn.commit()
            return True
        except Exception: return False

    def _verificar_mudanca_dia(self):
        if self._atualizar_estoque_automatico(): self.atualizar_lista_remedios()
        self.iniciar_loop_verificacao_diaria()

    def iniciar_loop_verificacao_diaria(self): self.root.after(600000, self._verificar_mudanca_dia)

    def atualizar_combo_pacientes_cadastro(self):
        pacientes = self.db_cursor.execute("SELECT nome FROM pacientes").fetchall()
        lista = [p[0] for p in pacientes]
        self.combo_paciente_cadastro['values'] = lista
        if lista and not self.combo_paciente_cadastro.get(): self.combo_paciente_cadastro.current(0)

    def atualizar_combo_filtro(self):
        pacientes = self.db_cursor.execute("SELECT nome FROM pacientes").fetchall()
        lista = ["Todos"] + [p[0] for p in pacientes]
        self.combo_filtro['values'] = lista
        if self.combo_filtro.get() == "": self.combo_filtro.current(0)

    def evento_filtro_mudou(self, event): self.atualizar_lista_remedios()

    def adicionar_paciente_dialog(self):
        nome = simpledialog.askstring("PharmaStock", "Nome do novo paciente:")
        if nome:
            try:
                self.db_cursor.execute("INSERT INTO pacientes (nome) VALUES (?)", (nome.strip(),))
                self.db_conn.commit()
                messagebox.showinfo("Sucesso", "Paciente adicionado com sucesso.")
                self.atualizar_combo_pacientes_cadastro()
                self.atualizar_combo_filtro()
                self.combo_paciente_cadastro.set(nome)
            except sqlite3.IntegrityError: messagebox.showerror("Erro", "Este paciente já está cadastrado.")

    def cadastrar_remedio(self):
        paciente_nome = self.combo_paciente_cadastro.get()
        nome_rem = self.entry_nome.get().strip()
        unidade = self.unidade_var.get()
        if not paciente_nome:
            messagebox.showerror("Erro", "Por favor, selecione um paciente.")
            return
        dias_indices = [str(i) for i, var in enumerate(self.vars_dias) if var.get()]
        dias_str = ",".join(dias_indices)
        if not dias_indices:
            messagebox.showerror("Erro", "Selecione ao menos um dia da semana.")
            return
        try:
            doses = int(self.entry_doses.get())
            estoque = int(self.entry_estoque.get())
        except ValueError:
            messagebox.showerror("Erro", "Dose e Estoque devem ser números.")
            return
        if not nome_rem or doses <= 0 or estoque < 0:
            messagebox.showerror("Erro", "Preencha todos os campos corretamente.")
            return
        try:
            self.db_cursor.execute("SELECT id FROM pacientes WHERE nome = ?", (paciente_nome,))
            paciente_id = self.db_cursor.fetchone()[0]
            self.db_cursor.execute("INSERT INTO remedios (nome, doses_por_dia, estoque_atual, unidade, paciente_id, dias_semana) VALUES (?, ?, ?, ?, ?, ?)", (nome_rem, doses, estoque, unidade, paciente_id, dias_str))
            self.db_conn.commit()
            self.entry_nome.delete(0, 'end')
            self.entry_doses.delete(0, 'end')
            self.entry_estoque.delete(0, 'end')
            messagebox.showinfo("Sucesso", "Medicamento cadastrado!")
            self.root.nametowidget(self.root.winfo_children()[1]).select(0) 
            filtro_atual = self.combo_filtro.get()
            if filtro_atual != "Todos" and filtro_atual != paciente_nome: self.combo_filtro.set(paciente_nome)
            self.atualizar_lista_remedios()
        except sqlite3.Error as e: messagebox.showerror("Erro BD", str(e))

    def calcular_previsao_inteligente(self, estoque, doses_por_dia, dias_str):
        if estoque <= 0: return 0, "Acabou!"
        dias_ativos = [int(d) for d in dias_str.split(',') if d]
        if not dias_ativos: return 999, "Sem dias definidos"
        dias_corridos = 0
        estoque_temp = estoque
        data_atual = date.today()
        while estoque_temp > 0 and dias_corridos < 1825: 
            dia_da_semana = data_atual.weekday()
            if dia_da_semana in dias_ativos: estoque_temp -= doses_por_dia
            if estoque_temp > 0:
                data_atual += timedelta(days=1)
                dias_corridos += 1
            else: break 
        return dias_corridos, data_atual.strftime("%d/%m/%Y")

    def atualizar_lista_remedios(self):
        for item in self.tree.get_children(): self.tree.delete(item)
        paciente_filtro = self.combo_filtro.get()
        try:
            base_query = "SELECT r.id, p.nome, r.nome, r.doses_por_dia, r.estoque_atual, r.unidade, r.dias_semana FROM remedios r JOIN pacientes p ON r.paciente_id = p.id"
            params = ()
            if paciente_filtro and paciente_filtro != "Todos":
                base_query += " WHERE p.nome = ?"
                params = (paciente_filtro,)
            base_query += " ORDER BY r.nome"
            dados = self.db_cursor.execute(base_query, params).fetchall()
            count = 0
            for rid, pac_nome, rem_nome, dose, estoque, unid, dias_str in dados:
                dias_restantes, data_fim = self.calcular_previsao_inteligente(estoque, dose, dias_str)
                dias_fmt = self._formatar_dias_extenso(dias_str)
                
                # --- APLICANDO FORMATAÇÃO INTELIGENTE NA UI ---
                dose_smart = self._formatar_qtd_smart(dose, unid)
                estoque_smart = self._formatar_qtd_smart(estoque, unid)

                tags_linha = []
                # LÓGICA ATUALIZADA: Apenas CRÍTICO (Vermelho) ou Zebra (Normal)
                if (dias_restantes <= 5 and estoque > 0) or estoque == 0: 
                    tags_linha = ['critico']
                else:
                    if count % 2 == 1: tags_linha.append('zebra')
                
                count += 1
                display_nome = rem_nome
                if paciente_filtro == "Todos": display_nome = f"{rem_nome} ({pac_nome})"
                
                self.tree.insert("", "end", iid=rid, values=(
                    display_nome, dose_smart, estoque_smart, dias_fmt, f"{dias_restantes} dias", data_fim
                ), tags=tuple(tags_linha))
                
        except sqlite3.Error as e: print(e)

    def get_selected_id(self):
        sel = self.tree.focus()
        if not sel:
            messagebox.showwarning("Atenção", "Selecione um medicamento na lista.")
            return None
        return int(sel)

    def ver_detalhes(self):
        rid = self.get_selected_id()
        if not rid: return
        try:
            query = "SELECT r.nome, p.nome, r.doses_por_dia, r.estoque_atual, r.unidade, r.dias_semana FROM remedios r JOIN pacientes p ON r.paciente_id = p.id WHERE r.id = ?"
            dados = self.db_cursor.execute(query, (rid,)).fetchone()
            if not dados: return
            nome_rem, nome_pac, dose, estoque, unid, dias_str = dados
            dias_restantes, data_fim = self.calcular_previsao_inteligente(estoque, dose, dias_str)
            dias_fmt = self._formatar_dias_extenso(dias_str)
            mensagem = (f"Medicamento: {nome_rem}\nPaciente: {nome_pac}\n----------------------------\nEstoque: {estoque} {unid}\nDose: {dose} {unid}\n----------------------------\nUso: {dias_fmt}\nTérmino: {data_fim} ({dias_restantes} dias)")
            messagebox.showinfo("Detalhes", mensagem)
        except sqlite3.Error as e: messagebox.showerror("Erro", f"Erro: {e}")

    def adicionar_estoque(self):
        rid = self.get_selected_id()
        if not rid: return
        dados = self.db_cursor.execute("SELECT nome, unidade FROM remedios WHERE id=?", (rid,)).fetchone()
        nome, unidade = dados
        qtd_str = simpledialog.askstring("Adicionar", f"Quantidade a adicionar ({unidade}):")
        if qtd_str:
            try:
                qtd = int(qtd_str)
                if qtd > 0:
                    self.db_cursor.execute("UPDATE remedios SET estoque_atual = estoque_atual + ? WHERE id=?", (qtd, rid))
                    self.db_conn.commit()
                    self.atualizar_lista_remedios()
            except ValueError: messagebox.showerror("Erro", "Valor inválido.")

    def modificar_estoque(self):
        rid = self.get_selected_id()
        if not rid: return
        dados = self.db_cursor.execute("SELECT nome, unidade FROM remedios WHERE id=?", (rid,)).fetchone()
        nome, unidade = dados
        qtd_str = simpledialog.askstring("Corrigir", f"Novo valor TOTAL ({unidade}):")
        if qtd_str is not None:
            try:
                qtd = int(qtd_str)
                if qtd >= 0:
                    self.db_cursor.execute("UPDATE remedios SET estoque_atual = ? WHERE id=?", (qtd, rid))
                    self.db_conn.commit()
                    self.atualizar_lista_remedios()
            except ValueError: messagebox.showerror("Erro", "Valor inválido.")

    def remover_remedio(self):
        rid = self.get_selected_id()
        if not rid: return
        if messagebox.askyesno("Confirmar", "Tem certeza que deseja apagar?"):
            self.db_cursor.execute("DELETE FROM remedios WHERE id=?", (rid,))
            self.db_conn.commit()
            self.atualizar_lista_remedios()

    def _verificar_estoque_notificacao(self):
        t_conn = sqlite3.connect(self.db_name)
        t_cur = t_conn.cursor()
        try:
            query = "SELECT r.nome, r.estoque_atual, r.unidade, r.doses_por_dia, r.dias_semana, p.nome FROM remedios r JOIN pacientes p ON r.paciente_id = p.id WHERE r.estoque_atual > 0"
            remedios = t_cur.execute(query).fetchall()
            for rem_nome, estoque, unid, dose, dias_str, pac_nome in remedios:
                dias_ativos = [int(d) for d in dias_str.split(',') if d]
                dias_restantes = 999
                if dias_ativos:
                    temp_est = estoque
                    temp_dias = 0
                    curr_date = date.today()
                    while temp_est > 0 and temp_dias < 365:
                        if curr_date.weekday() in dias_ativos: temp_est -= dose
                        if temp_est > 0:
                            curr_date += timedelta(days=1)
                            temp_dias += 1
                    dias_restantes = temp_dias
                if dias_restantes <= 5:
                    msg = f"{rem_nome} ({pac_nome}) está acabando! Restam {estoque} {unid}."
                    self.root.after(0, self.enviar_notificacao_limpa, "Alerta PharmaStock", msg)
                    time.sleep(5) 
        except Exception: pass
        finally: t_conn.close()

    def _loop_notificacao(self):
        time.sleep(5)
        while True:
            self._verificar_estoque_notificacao()
            time.sleep(3600)

    def iniciar_verificador_notificacoes(self):
        t = threading.Thread(target=self._loop_notificacao, daemon=True)
        t.start()

    def testar_notificacao_agora(self):
        messagebox.showinfo("Teste", "Verificação iniciada. Se houver alertas, uma notificação aparecerá em breve.")
        threading.Thread(target=self._verificar_estoque_notificacao).start()

    def mostrar_janela_tray(self): self.root.after(0, self.mostrar_janela)
    def sair_app_tray(self): self.root.after(0, self.sair_app)
    def esconder_janela(self): self.root.withdraw()
    def mostrar_janela(self):
        self.root.deiconify()
        self.root.lift()
    def sair_app(self):
        if self.tray_icon: self.tray_icon.stop()
        if self.db_conn: self.db_conn.close()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()