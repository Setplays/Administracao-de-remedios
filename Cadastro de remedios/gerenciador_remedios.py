import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import sqlite3
import os
import sys
from datetime import datetime, timedelta, date
import threading
import time

# --- Configurações Iniciais ---
try:
    from win10toast import ToastNotifier
    NOTIFIER_AVAILABLE = True
except ImportError:
    NOTIFIER_AVAILABLE = False
    ToastNotifier = None

try:
    from pystray import Icon as TrayIcon, Menu, MenuItem
    from PIL import Image, ImageTk
    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False

DB_PATH = os.path.join(os.path.expanduser("~"), "pharmastock.db")

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

# --- Validadores ---
def is_val_too_big(valores: tuple):
    MAX_VALUE = 10_000_000
    for val in valores:
        if val > MAX_VALUE:
            messagebox.showerror("Erro", f"Valor muito alto. Máx: {MAX_VALUE}")
            return True
    return False

def is_str_too_big(word):
    MAX_VALUE = 50
    if len(word) > MAX_VALUE:
        messagebox.showerror("Erro", f"Texto muito grande. Máx: {MAX_VALUE} caracteres.")
        return True
    return False

class App:
    def __init__(self, root):
        self.root = root
        self.db_name = DB_PATH
        self.db_conn = None
        self.db_cursor = None
        self.toaster = None
        
        global NOTIFIER_AVAILABLE
        
        self.root.title("PharmaStock - Gerenciamento Completo")
        self.root.geometry("1100x750")

        if NOTIFIER_AVAILABLE:
            try:
                self.toaster = ToastNotifier()
            except Exception:
                NOTIFIER_AVAILABLE = False

        self._init_db()
        self._setup_ui()
        
        self.atualizar_combo_pacientes_cadastro()
        self.atualizar_combo_filtro()
        self.atualizar_lista_remedios()

        self.iniciar_verificador_notificacoes()
        self.iniciar_loop_verificacao_diaria()

        self.tray_icon = None
        if TRAY_AVAILABLE:
            self.setup_tray_icon()
            self.root.protocol("WM_DELETE_WINDOW", self.esconder_janela)
        else:
            self.root.protocol("WM_DELETE_WINDOW", self.sair_app)
            
        if "--minimized" in sys.argv and TRAY_AVAILABLE:
            self.esconder_janela()

    def _init_db(self):
        try:
            self.db_conn = sqlite3.connect(self.db_name)
            self.db_cursor = self.db_conn.cursor()
            self.db_cursor.execute("PRAGMA foreign_keys = ON;")

            self.db_cursor.execute("""
            CREATE TABLE IF NOT EXISTS pacientes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL UNIQUE
            )
            """)
            
            self.db_cursor.execute("SELECT count(*) FROM pacientes")
            if self.db_cursor.fetchone()[0] == 0:
                self.db_cursor.execute("INSERT INTO pacientes (nome) VALUES ('Principal')")

            self.db_cursor.execute("""
            CREATE TABLE IF NOT EXISTS remedios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                doses_por_dia INTEGER NOT NULL,
                estoque_atual INTEGER NOT NULL DEFAULT 0,
                unidade TEXT NOT NULL DEFAULT 'comprimido',
                paciente_id INTEGER,
                dias_semana TEXT DEFAULT '0,1,2,3,4,5,6',
                FOREIGN KEY(paciente_id) REFERENCES pacientes(id) ON DELETE CASCADE
            )
            """)
            
            self.db_cursor.execute("""
            CREATE TABLE IF NOT EXISTS app_info (
                id INTEGER PRIMARY KEY,
                last_run_date TEXT NOT NULL
            )
            """)
            
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
            if last_run >= hoje:
                return False

            remedios = self.db_cursor.execute("SELECT id, doses_por_dia, estoque_atual, dias_semana FROM remedios").fetchall()
            
            debitou = False
            for rem_id, doses, estoque, dias_str in remedios:
                if estoque <= 0: continue
                
                dias_ativos = [int(d) for d in dias_str.split(',') if d]
                consumo = 0
                temp_date = last_run + timedelta(days=1)
                
                while temp_date <= hoje:
                    if temp_date.weekday() in dias_ativos:
                        consumo += doses
                    temp_date += timedelta(days=1)
                
                if consumo > 0:
                    novo = max(0, estoque - consumo)
                    self.db_cursor.execute("UPDATE remedios SET estoque_atual = ? WHERE id = ?", (novo, rem_id))
                    debitou = True

            self.db_cursor.execute("UPDATE app_info SET last_run_date = ? WHERE id = 1", (hoje.strftime('%Y-%m-%d'),))
            self.db_conn.commit()
            return debitou
        except Exception as e:
            print(f"Erro update auto: {e}")
            return False

    def _verificar_mudanca_dia(self):
        if self._atualizar_estoque_automatico():
            self.atualizar_lista_remedios()
        self.iniciar_loop_verificacao_diaria()

    def iniciar_loop_verificacao_diaria(self):
        self.root.after(600000, self._verificar_mudanca_dia)

    def _setup_ui(self):
        style = ttk.Style()
        style.configure("Treeview", rowheight=25)
        style.configure("Bold.TLabel", font=('Segoe UI', 9, 'bold'))

        # --- Frame de Cadastro (Topo) ---
        cadastro_frame = ttk.LabelFrame(self.root, text="Cadastrar Novo Medicamento", padding=(10, 10))
        cadastro_frame.pack(fill="x", padx=10, pady=5)

        # Seleção de Paciente
        ttk.Label(cadastro_frame, text="Paciente:").grid(row=0, column=0, padx=5, sticky="e")
        self.combo_paciente_cadastro = ttk.Combobox(cadastro_frame, state="readonly", width=25)
        self.combo_paciente_cadastro.grid(row=0, column=1, padx=5, sticky="w")
        
        btn_novo_pac = ttk.Button(cadastro_frame, text="+ Novo", width=8, command=self.adicionar_paciente_dialog)
        btn_novo_pac.grid(row=0, column=2, padx=2, sticky="w")

        # Dados do Remédio
        ttk.Label(cadastro_frame, text="Nome do Medicamento:").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        self.entry_nome = ttk.Entry(cadastro_frame, width=40)
        self.entry_nome.grid(row=1, column=1, columnspan=2, padx=5, sticky="we")

        ttk.Label(cadastro_frame, text="Dose Diária:").grid(row=2, column=0, padx=5, sticky="e")
        self.entry_doses = ttk.Entry(cadastro_frame, width=10)
        self.entry_doses.grid(row=2, column=1, padx=5, sticky="w")
        
        ttk.Label(cadastro_frame, text="Estoque Inicial:").grid(row=2, column=1, padx=(120, 5), sticky="w")
        self.entry_estoque = ttk.Entry(cadastro_frame, width=10)
        self.entry_estoque.grid(row=2, column=1, padx=(210, 5), sticky="w")

        # Unidade
        ttk.Label(cadastro_frame, text="Tipo de Unidade:").grid(row=3, column=0, padx=5, sticky="e")
        unidade_frame = ttk.Frame(cadastro_frame)
        unidade_frame.grid(row=3, column=1, columnspan=3, sticky="w")
        self.unidade_var = tk.StringVar(value="comprimido")
        ttk.Radiobutton(unidade_frame, text="Comprimido", variable=self.unidade_var, value="comprimido").pack(side="left")
        ttk.Radiobutton(unidade_frame, text="ML", variable=self.unidade_var, value="ml").pack(side="left", padx=10)
        ttk.Radiobutton(unidade_frame, text="Unidade Genérica", variable=self.unidade_var, value="unidade").pack(side="left", padx=10)

        # Dias da Semana - CORREÇÃO: DIVIDIDO EM 2 LINHAS
        lbl_dias = ttk.Label(cadastro_frame, text="Dias de Uso:")
        lbl_dias.grid(row=4, column=0, padx=5, pady=5, sticky="ne")
        dias_frame = ttk.Frame(cadastro_frame)
        dias_frame.grid(row=4, column=1, columnspan=4, sticky="w")
        
        self.vars_dias = []
        dias_nomes = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
        
        for i, nome in enumerate(dias_nomes):
            var = tk.BooleanVar(value=True)
            chk = ttk.Checkbutton(dias_frame, text=nome, variable=var)
            
            # Divide: Primeiros 4 na linha 0, Restantes 3 na linha 1
            if i < 4:
                chk.grid(row=0, column=i, padx=5, sticky="w")
            else:
                chk.grid(row=1, column=i-4, padx=5, sticky="w")
                
            self.vars_dias.append(var)

        self.btn_cadastrar = ttk.Button(cadastro_frame, text="CADASTRAR MEDICAMENTO", command=self.cadastrar_remedio)
        self.btn_cadastrar.grid(row=0, column=4, rowspan=5, padx=20, sticky="ns")

        # --- Frame de Visualização (Centro) ---
        visualizacao_frame = ttk.LabelFrame(self.root, text="Controle de Estoque e Previsão", padding=(10, 10))
        visualizacao_frame.pack(fill="both", expand=True, padx=10, pady=5)

        # Filtro
        filtro_frame = ttk.Frame(visualizacao_frame)
        filtro_frame.pack(fill="x", pady=(0, 10))
        
        ttk.Label(filtro_frame, text="Filtrar visualização por Paciente:", style="Bold.TLabel").pack(side="left", padx=5)
        self.combo_filtro = ttk.Combobox(filtro_frame, state="readonly", width=30)
        self.combo_filtro.pack(side="left", padx=5)
        self.combo_filtro.bind("<<ComboboxSelected>>", self.evento_filtro_mudou)

        # Treeview
        colunas = ("remedio", "dose", "estoque", "dias_rest", "previsao")
        self.tree = ttk.Treeview(visualizacao_frame, columns=colunas, show="headings")
        
        self.tree.heading("remedio", text="Nome do Medicamento")
        self.tree.heading("dose", text="Dose Diária")
        self.tree.heading("estoque", text="Estoque Atual")
        self.tree.heading("dias_rest", text="Dias Restantes")
        self.tree.heading("previsao", text="Previsão de Término")

        self.tree.column("remedio", width=300)
        self.tree.column("dose", width=120, anchor="center")
        self.tree.column("estoque", width=120, anchor="center")
        self.tree.column("dias_rest", width=120, anchor="center")
        self.tree.column("previsao", width=150, anchor="center")

        self.tree.tag_configure('critico', foreground='red') 

        scrollbar = ttk.Scrollbar(visualizacao_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)

        # --- Frame de Ações (Baixo) ---
        acoes_frame = ttk.Frame(self.root)
        acoes_frame.pack(fill="x", padx=10, pady=10)
        
        ttk.Button(acoes_frame, text="Adicionar Estoque", command=self.adicionar_estoque).pack(side="left", padx=5)
        ttk.Button(acoes_frame, text="Corrigir Estoque Manualmente", command=self.modificar_estoque).pack(side="left", padx=5)
        ttk.Button(acoes_frame, text="Remover Medicamento", command=self.remover_remedio).pack(side="left", padx=5)
        
        ttk.Button(acoes_frame, text="Ver Detalhes Completos", command=self.ver_detalhes).pack(side="left", padx=20)
        
        ttk.Button(acoes_frame, text="Testar Alerta de Estoque", command=self.testar_notificacao_agora).pack(side="right", padx=5)

    # --- Lógica de Pacientes e Filtros ---
    def atualizar_combo_pacientes_cadastro(self):
        pacientes = self.db_cursor.execute("SELECT nome FROM pacientes").fetchall()
        lista = [p[0] for p in pacientes]
        self.combo_paciente_cadastro['values'] = lista
        if lista and not self.combo_paciente_cadastro.get():
            self.combo_paciente_cadastro.current(0)

    def atualizar_combo_filtro(self):
        pacientes = self.db_cursor.execute("SELECT nome FROM pacientes").fetchall()
        lista = ["Todos"] + [p[0] for p in pacientes]
        self.combo_filtro['values'] = lista
        if self.combo_filtro.get() == "":
            self.combo_filtro.current(0)

    def evento_filtro_mudou(self, event):
        self.atualizar_lista_remedios()

    def adicionar_paciente_dialog(self):
        nome = simpledialog.askstring("PharmaStock", "Nome do novo paciente:")
        if nome:
            if is_str_too_big(nome): return
            try:
                self.db_cursor.execute("INSERT INTO pacientes (nome) VALUES (?)", (nome.strip(),))
                self.db_conn.commit()
                messagebox.showinfo("Sucesso", "Paciente adicionado com sucesso.")
                self.atualizar_combo_pacientes_cadastro()
                self.atualizar_combo_filtro()
                self.combo_paciente_cadastro.set(nome)
            except sqlite3.IntegrityError:
                messagebox.showerror("Erro", "Este paciente já está cadastrado.")

    # --- Lógica de Remédios ---
    def cadastrar_remedio(self):
        paciente_nome = self.combo_paciente_cadastro.get()
        nome_rem = self.entry_nome.get().strip()
        unidade = self.unidade_var.get()
        
        if not paciente_nome:
            messagebox.showerror("Erro", "Por favor, selecione um paciente para o cadastro.")
            return

        dias_indices = [str(i) for i, var in enumerate(self.vars_dias) if var.get()]
        dias_str = ",".join(dias_indices)
        
        if not dias_indices:
            messagebox.showerror("Erro", "Selecione ao menos um dia da semana para o uso.")
            return

        try:
            doses = int(self.entry_doses.get())
            estoque = int(self.entry_estoque.get())
        except ValueError:
            messagebox.showerror("Erro", "Dose e Estoque devem ser números inteiros.")
            return

        if not nome_rem or doses <= 0 or estoque < 0:
            messagebox.showerror("Erro", "Preencha todos os campos corretamente.")
            return

        try:
            self.db_cursor.execute("SELECT id FROM pacientes WHERE nome = ?", (paciente_nome,))
            paciente_id = self.db_cursor.fetchone()[0]

            self.db_cursor.execute("""
                INSERT INTO remedios (nome, doses_por_dia, estoque_atual, unidade, paciente_id, dias_semana)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (nome_rem, doses, estoque, unidade, paciente_id, dias_str))
            
            self.db_conn.commit()
            
            self.entry_nome.delete(0, 'end')
            self.entry_doses.delete(0, 'end')
            self.entry_estoque.delete(0, 'end')
            messagebox.showinfo("Sucesso", "Medicamento cadastrado com sucesso!")
            
            filtro_atual = self.combo_filtro.get()
            if filtro_atual != "Todos" and filtro_atual != paciente_nome:
                self.combo_filtro.set(paciente_nome)
                
            self.atualizar_lista_remedios()
            
        except sqlite3.Error as e:
            messagebox.showerror("Erro BD", str(e))

    def calcular_previsao_inteligente(self, estoque, doses_por_dia, dias_str):
        if estoque <= 0: return 0, "Acabou!"
        if not dias_str: return 999, "Indefinido"
        
        dias_ativos = [int(d) for d in dias_str.split(',') if d]
        if not dias_ativos: return 999, "Sem dias definidos"

        dias_corridos = 0
        estoque_temp = estoque
        data_atual = date.today()

        while estoque_temp > 0 and dias_corridos < 1825: 
            dia_da_semana = data_atual.weekday()
            if dia_da_semana in dias_ativos:
                estoque_temp -= doses_por_dia
            
            if estoque_temp > 0:
                data_atual += timedelta(days=1)
                dias_corridos += 1
            else:
                break 

        return dias_corridos, data_atual.strftime("%d/%m/%Y")

    def atualizar_lista_remedios(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        paciente_filtro = self.combo_filtro.get()
        
        try:
            base_query = """
                SELECT r.id, p.nome, r.nome, r.doses_por_dia, r.estoque_atual, r.unidade, r.dias_semana
                FROM remedios r
                JOIN pacientes p ON r.paciente_id = p.id
            """
            
            params = ()
            if paciente_filtro and paciente_filtro != "Todos":
                base_query += " WHERE p.nome = ?"
                params = (paciente_filtro,)
                
            base_query += " ORDER BY r.nome"
            
            dados = self.db_cursor.execute(base_query, params).fetchall()
            
            for rid, pac_nome, rem_nome, dose, estoque, unid, dias_str in dados:
                dias_restantes, data_fim = self.calcular_previsao_inteligente(estoque, dose, dias_str)
                
                tags_linha = ()
                if (dias_restantes <= 5 and estoque > 0) or estoque == 0:
                    tags_linha = ('critico',)
                
                display_nome = rem_nome
                if paciente_filtro == "Todos":
                    display_nome = f"{rem_nome} ({pac_nome})"
                
                self.tree.insert("", "end", iid=rid, values=(
                    display_nome, f"{dose} {unid}", f"{estoque} {unid}", f"{dias_restantes} dias", data_fim
                ), tags=tags_linha)
                
        except sqlite3.Error as e:
            print(e)

    def get_selected_id(self):
        sel = self.tree.focus()
        if not sel:
            messagebox.showwarning("Atenção", "Por favor, selecione um medicamento na lista primeiro.")
            return None
        return int(sel)

    def ver_detalhes(self):
        rid = self.get_selected_id()
        if not rid: return

        try:
            query = """
                SELECT r.nome, p.nome, r.doses_por_dia, r.estoque_atual, r.unidade, r.dias_semana
                FROM remedios r
                JOIN pacientes p ON r.paciente_id = p.id
                WHERE r.id = ?
            """
            dados = self.db_cursor.execute(query, (rid,)).fetchone()
            if not dados: return

            nome_rem, nome_pac, dose, estoque, unid, dias_str = dados
            dias_restantes, data_fim = self.calcular_previsao_inteligente(estoque, dose, dias_str)

            mapa_dias = {
                0: "Segunda", 1: "Terça", 2: "Quarta", 3: "Quinta", 
                4: "Sexta", 5: "Sábado", 6: "Domingo"
            }
            dias_ativos = [mapa_dias[int(d)] for d in dias_str.split(',') if d]
            dias_formatados = ", ".join(dias_ativos) if dias_ativos else "Nenhum dia selecionado"

            mensagem = (
                f"Medicamento: {nome_rem}\n"
                f"Paciente: {nome_pac}\n"
                f"----------------------------\n"
                f"Estoque Atual: {estoque} {unid}\n"
                f"Dose Prescrita: {dose} {unid} (nos dias de uso)\n"
                f"----------------------------\n"
                f"Dias de Uso na Semana:\n{dias_formatados}\n"
                f"----------------------------\n"
                f"Previsão de Término: {data_fim}\n"
                f"(Restam {dias_restantes} dias efetivos de medicação)"
            )
            
            messagebox.showinfo("Detalhes Completos do Medicamento", mensagem)

        except sqlite3.Error as e:
            messagebox.showerror("Erro", f"Erro ao buscar detalhes: {e}")

    def adicionar_estoque(self):
        rid = self.get_selected_id()
        if not rid: return
        dados = self.db_cursor.execute("SELECT nome, unidade FROM remedios WHERE id=?", (rid,)).fetchone()
        nome, unidade = dados
        
        qtd_str = simpledialog.askstring("Adicionar Estoque", f"Quantos '{unidade}' você quer adicionar ao estoque de {nome}?")
        if qtd_str:
            try:
                qtd = int(qtd_str)
                if qtd > 0:
                    self.db_cursor.execute("UPDATE remedios SET estoque_atual = estoque_atual + ? WHERE id=?", (qtd, rid))
                    self.db_conn.commit()
                    self.atualizar_lista_remedios()
            except ValueError:
                messagebox.showerror("Erro", "Valor inválido.")

    def modificar_estoque(self):
        rid = self.get_selected_id()
        if not rid: return
        dados = self.db_cursor.execute("SELECT nome, unidade FROM remedios WHERE id=?", (rid,)).fetchone()
        nome, unidade = dados

        qtd_str = simpledialog.askstring("Correção Manual", f"Qual é o valor EXATO que está na caixa de {nome} agora?")
        if qtd_str is not None:
            try:
                qtd = int(qtd_str)
                if qtd >= 0:
                    self.db_cursor.execute("UPDATE remedios SET estoque_atual = ? WHERE id=?", (qtd, rid))
                    self.db_conn.commit()
                    self.atualizar_lista_remedios()
            except ValueError:
                 messagebox.showerror("Erro", "Valor inválido.")

    def remover_remedio(self):
        rid = self.get_selected_id()
        if not rid: return
        if messagebox.askyesno("Confirmar Exclusão", "Tem certeza que deseja apagar este medicamento do sistema?"):
            self.db_cursor.execute("DELETE FROM remedios WHERE id=?", (rid,))
            self.db_conn.commit()
            self.atualizar_lista_remedios()

    def _verificar_estoque_notificacao(self):
        if not NOTIFIER_AVAILABLE: return
        t_conn = sqlite3.connect(self.db_name)
        t_cur = t_conn.cursor()
        try:
            query = """
                SELECT r.nome, r.estoque_atual, r.unidade, r.doses_por_dia, r.dias_semana, p.nome
                FROM remedios r
                JOIN pacientes p ON r.paciente_id = p.id
                WHERE r.estoque_atual > 0
            """
            remedios = t_cur.execute(query).fetchall()
            for rem_nome, estoque, unid, dose, dias_str, pac_nome in remedios:
                dias_ativos = [int(d) for d in dias_str.split(',') if d]
                dias_restantes = 999
                if dias_ativos:
                    temp_est = estoque
                    temp_dias = 0
                    curr_date = date.today()
                    while temp_est > 0 and temp_dias < 365:
                        if curr_date.weekday() in dias_ativos:
                            temp_est -= dose
                        if temp_est > 0:
                            curr_date += timedelta(days=1)
                            temp_dias += 1
                    dias_restantes = temp_dias
                
                if dias_restantes <= 5:
                    msg = f"Atenção: {rem_nome} ({pac_nome}) está acabando! Restam {estoque} {unid}."
                    self.root.after(0, self.agendar_notificacao_main_thread, "PharmaStock - Alerta de Estoque", msg)
                    time.sleep(2)
        except Exception:
            pass
        finally:
            t_conn.close()

    def agendar_notificacao_main_thread(self, titulo, mensagem):
        if self.toaster:
            try:
                self.toaster.show_toast(titulo, mensagem, duration=5, threaded=True)
            except: pass

    def _loop_notificacao(self):
        time.sleep(5)
        while True:
            self._verificar_estoque_notificacao()
            time.sleep(3600)

    def iniciar_verificador_notificacoes(self):
        t = threading.Thread(target=self._loop_notificacao, daemon=True)
        t.start()

    def testar_notificacao_agora(self):
        if not NOTIFIER_AVAILABLE:
            messagebox.showinfo("Info", "O sistema de notificações não está disponível neste computador.")
            return
        threading.Thread(target=self._verificar_estoque_notificacao).start()
        messagebox.showinfo("PharmaStock", "Verificando estoque e gerando alertas de teste...")

    def setup_tray_icon(self):
        try:
            img = Image.open(resource_path("cardiogram.png"))
            menu = Menu(MenuItem('Abrir PharmaStock', self.mostrar_janela_tray, default=True), MenuItem('Sair', self.sair_app_tray))
            self.tray_icon = TrayIcon("PharmaStock", img, "PharmaStock", menu)
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
        except Exception:
            global TRAY_AVAILABLE
            TRAY_AVAILABLE = False

    def mostrar_janela_tray(self):
        self.root.after(0, self.mostrar_janela)

    def sair_app_tray(self):
        self.root.after(0, self.sair_app)

    def esconder_janela(self):
        self.root.withdraw()
        if not TRAY_AVAILABLE:
            self.root.quit()

    def mostrar_janela(self):
        self.root.deiconify()
        self.root.lift()

    def sair_app(self):
        if self.tray_icon: self.tray_icon.stop()
        if self.db_conn: self.db_conn.close()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    try:
        icone = ImageTk.PhotoImage(Image.open(resource_path("cardiogram.png")))
        root.iconphoto(True, icone)
    except: pass
    app = App(root)
    root.mainloop()