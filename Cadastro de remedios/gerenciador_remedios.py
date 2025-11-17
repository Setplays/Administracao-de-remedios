import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import sqlite3
import os
import sys
from datetime import datetime, timedelta, date
import threading
import time

# --- Tenta importar bibliotecas externas ---
try:
    from win10toast import ToastNotifier
    NOTIFIER_AVAILABLE = True
except ImportError:
    print("Biblioteca 'win10toast' não encontrada.")
    print("O programa funcionará, mas sem notificações.")
    print("Para instalar, use: pip install win10toast")
    NOTIFIER_AVAILABLE = False
    ToastNotifier = None

try:
    from pystray import Icon as TrayIcon, Menu, MenuItem
    from PIL import Image, ImageTk # Importa ImageTk para carregar o ícone
    TRAY_AVAILABLE = True
except ImportError:
    print("Bibliotecas 'pystray' ou 'Pillow' não encontradas.")
    print("O programa funcionará em modo de janela normal.")
    print("Para instalar, use: pip install pystray pillow")
    TRAY_AVAILABLE = False
# --- Fim das Importações ---

# --- Configuração de Caminhos ---
DB_PATH = os.path.join(os.path.expanduser("~"), "remedios.db")

def resource_path(relative_path):
    """
    Obtém o caminho absoluto para um recurso (como ícones),
    funciona tanto em modo de desenvolvimento quanto no executável do PyInstaller.
    """
    try:
        # PyInstaller cria uma pasta temporária e armazena o caminho em _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        # Modo de desenvolvimento (não está "congelado")
        # CORREÇÃO: Usa o diretório do *arquivo .py* e não o diretório de trabalho
        base_path = os.path.dirname(os.path.abspath(__file__))

    return os.path.join(base_path, relative_path)


class App:
    """Classe principal do aplicativo Gerenciador de Remédios."""

    def __init__(self, root):
        self.root = root
        self.db_name = DB_PATH
        self.db_conn = None
        self.db_cursor = None
        self.toaster = None
        
        global NOTIFIER_AVAILABLE
        
        self.root.title("Gerenciador de Remédios")
        self.root.geometry("800x600")

        if NOTIFIER_AVAILABLE:
            try:
                self.toaster = ToastNotifier()
                print("Notificador (win10toast) inicializado com sucesso.")
            except Exception as e:
                print(f"Erro ao inicializar o ToastNotifier: {e}")
                print("Desativando notificações.")
                NOTIFIER_AVAILABLE = False

        self._init_db()
        self._setup_ui()
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
            print("Iniciando minimizado...")
            self.esconder_janela()
        else:
            self.root.deiconify()

    def _check_and_add_column(self, table_name, column_name, column_definition):
        """Verifica se uma coluna existe e, se não, a adiciona."""
        try:
            self.db_cursor.execute(f"PRAGMA table_info({table_name})")
            columns = [info[1] for info in self.db_cursor.fetchall()]
            if column_name not in columns:
                print(f"Adicionando coluna '{column_name}' à tabela '{table_name}'...")
                self.db_cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")
                self.db_conn.commit()
                print(f"Coluna '{column_name}' adicionada com sucesso.")
        except sqlite3.Error as e:
            print(f"Erro ao tentar adicionar coluna '{column_name}': {e}")

    def _init_db(self):
        """Inicializa a conexão com o banco de dados e cria/atualiza as tabelas."""
        try:
            print(f"Usando banco de dados em: {self.db_name}")
            self.db_conn = sqlite3.connect(self.db_name)
            self.db_cursor = self.db_conn.cursor()
            
            self.db_cursor.execute("PRAGMA foreign_keys = ON;")

            # Tabela de Remédios
            self.db_cursor.execute("""
            CREATE TABLE IF NOT EXISTS remedios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL UNIQUE,
                doses_por_dia INTEGER NOT NULL,
                estoque_atual INTEGER NOT NULL DEFAULT 0
            )
            """)

            # Tabela de Histórico de Estoque
            self.db_cursor.execute("""
            CREATE TABLE IF NOT EXISTS historico_estoque (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                remedio_id INTEGER NOT NULL,
                quantidade_adicionada INTEGER NOT NULL,
                data_adicao DATE NOT NULL,
                FOREIGN KEY (remedio_id) REFERENCES remedios (id) ON DELETE CASCADE
            )
            """)
            
            # Tabela para rastrear a última execução
            self.db_cursor.execute("""
            CREATE TABLE IF NOT EXISTS app_info (
                id INTEGER PRIMARY KEY,
                last_run_date TEXT NOT NULL
            )
            """)
            
            # --- NOVO: Adiciona a coluna 'unidade' se ela não existir ---
            self._check_and_add_column('remedios', 'unidade', 'TEXT NOT NULL DEFAULT "comprimido"')
            
            self.db_conn.commit()
            
            self._atualizar_estoque_automatico()

        except sqlite3.Error as e:
            messagebox.showerror("Erro de Banco de Dados", f"Erro ao conectar ao SQLite: {e}")
            self.root.quit()

    def _atualizar_estoque_automatico(self, dias_passados=None):
        """Debita o estoque dos remédios com base nos dias que se passaram."""
        try:
            hoje = date.today()
            hoje_str = hoje.strftime('%Y-%m-%d')
            dias_a_debitar = 0
            
            if dias_passados is None:
                self.db_cursor.execute("SELECT last_run_date FROM app_info WHERE id = 1")
                resultado = self.db_cursor.fetchone()
                
                if resultado:
                    last_run_date_str = resultado[0]
                    last_run_date = datetime.strptime(last_run_date_str, '%Y-%m-%d').date()
                    dias_a_debitar = (hoje - last_run_date).days
                else:
                    print("Primeira execução. Configurando data de verificação de estoque.")
                    self.db_cursor.execute("INSERT INTO app_info (id, last_run_date) VALUES (1, ?)", (hoje_str,))
                    self.db_conn.commit()
                    return False
            else:
                dias_a_debitar = dias_passados

            
            if dias_a_debitar > 0:
                print(f"Detectado {dias_a_debitar} dia(s) para debitar. Atualizando estoque...")
                
                self.db_cursor.execute("""
                    UPDATE remedios
                    SET estoque_atual = MAX(0, estoque_atual - (doses_por_dia * ?))
                    WHERE doses_por_dia > 0
                """, (dias_a_debitar,))
                
                self.db_cursor.execute("UPDATE app_info SET last_run_date = ? WHERE id = 1", (hoje_str,))
                self.db_conn.commit()
                print(f"Estoque debitado por {dias_a_debitar} dia(s).")
                
                return True 
            else:
                print("Verificação automática de estoque: Nenhum dia se passou.")
                return False

        except sqlite3.Error as e:
            print(f"Erro ao atualizar estoque automático: {e}")
            messagebox.showwarning("Erro de Atualização", f"Não foi possível atualizar o estoque automático: {e}")
            return False

    def _verificar_mudanca_dia(self):
        """Chamado pelo loop 'root.after' para verificar se a data mudou."""
        try:
            self.db_cursor.execute("SELECT last_run_date FROM app_info WHERE id = 1")
            resultado = self.db_cursor.fetchone()
            
            if resultado:
                last_run_date_str = resultado[0]
                last_run_date = datetime.strptime(last_run_date_str, '%Y-%m-%d').date()
                hoje = date.today()
                
                dias_passados = (hoje - last_run_date).days
                
                if dias_passados > 0:
                    print(f"MEIA-NOITE DETECTADA! Passaram {dias_passados} dia(s).")
                    if self._atualizar_estoque_automatico(dias_passados=dias_passados):
                        self.atualizar_lista_remedios()
        
        except sqlite3.Error as e:
            print(f"Erro no loop de verificação diária: {e}")
        except Exception as e:
            print(f"Erro inesperado no loop de verificação diária: {e}")
        finally:
            self.iniciar_loop_verificacao_diaria() # Re-agenda

    def iniciar_loop_verificacao_diaria(self):
        """Agenda a próxima verificação de mudança de dia."""
        self.root.after(600000, self._verificar_mudanca_dia) # A cada 10 minutos


    def _setup_ui(self):
        """Cria e organiza os widgets da interface gráfica."""
        
        # --- Frame de Cadastro ---
        cadastro_frame = ttk.LabelFrame(self.root, text="Cadastrar Novo Remédio", padding=(10, 10))
        cadastro_frame.pack(fill="x", padx=10, pady=10)
        cadastro_frame.columnconfigure(1, weight=1)

        # Linha 0: Nome
        ttk.Label(cadastro_frame, text="Nome:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        self.entry_nome = ttk.Entry(cadastro_frame, width=40)
        self.entry_nome.grid(row=0, column=1, columnspan=3, padx=5, pady=5, sticky="we")

        # Linha 1: Doses e Estoque
        ttk.Label(cadastro_frame, text="Dose Diária:").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        self.entry_doses_dia = ttk.Entry(cadastro_frame, width=10)
        self.entry_doses_dia.grid(row=1, column=1, padx=5, pady=5, sticky="w")

        ttk.Label(cadastro_frame, text="Estoque Inicial:").grid(row=1, column=2, padx=5, pady=5, sticky="e")
        self.entry_estoque = ttk.Entry(cadastro_frame, width=10)
        self.entry_estoque.grid(row=1, column=3, padx=5, pady=5, sticky="w")
        
        # --- NOVO: Linha 2: Unidade ---
        ttk.Label(cadastro_frame, text="Unidade:").grid(row=2, column=0, padx=5, pady=5, sticky="e")
        unidade_frame = ttk.Frame(cadastro_frame)
        unidade_frame.grid(row=2, column=1, columnspan=3, padx=5, pady=5, sticky="w")
        
        self.unidade_var = tk.StringVar(value="comprimido")
        ttk.Radiobutton(unidade_frame, text="Comprimido(s)", variable=self.unidade_var, value="comprimido").pack(side="left", padx=5)
        ttk.Radiobutton(unidade_frame, text="ML", variable=self.unidade_var, value="ml").pack(side="left", padx=5)
        
        # Botão de Cadastrar
        self.btn_cadastrar = ttk.Button(cadastro_frame, text="Cadastrar", command=self.cadastrar_remedio)
        self.btn_cadastrar.grid(row=0, column=4, rowspan=3, padx=10, pady=5, ipady=15) # rowspan=3 agora


        # --- Frame da Lista de Remédios ---
        lista_frame = ttk.LabelFrame(self.root, text="Meus Remédios", padding=(10, 10))
        lista_frame.pack(fill="both", expand=True, padx=10, pady=5)

        # Colunas atualizadas
        colunas = ("remedio", "dose", "estoque", "dias_restantes", "data_fim")
        self.tree = ttk.Treeview(lista_frame, columns=colunas, show="headings")

        self.tree.heading("remedio", text="Remédio")
        self.tree.heading("dose", text="Dose Diária") # Texto atualizado
        self.tree.heading("estoque", text="Estoque Atual") # Texto atualizado
        self.tree.heading("dias_restantes", text="Dias Restantes")
        self.tree.heading("data_fim", text="Data Prev. Fim")

        self.tree.column("remedio", width=250)
        self.tree.column("dose", width=120, anchor="center")
        self.tree.column("estoque", width=120, anchor="center")
        self.tree.column("dias_restantes", width=100, anchor="center")
        self.tree.column("data_fim", width=120, anchor="center")

        scrollbar = ttk.Scrollbar(lista_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)

        # --- Frame de Ações ---
        acoes_frame = ttk.Frame(self.root, padding=(10, 0))
        acoes_frame.pack(fill="x", padx=10, pady=10)

        self.btn_add_estoque = ttk.Button(acoes_frame, text="Adicionar Estoque", command=self.adicionar_estoque)
        self.btn_add_estoque.pack(side="left", padx=5)

        self.btn_mod_estoque = ttk.Button(acoes_frame, text="Modificar Estoque", command=self.modificar_estoque)
        self.btn_mod_estoque.pack(side="left", padx=5)

        self.btn_remover = ttk.Button(acoes_frame, text="Remover Remédio", command=self.remover_remedio_selecionado)
        self.btn_remover.pack(side="left", padx=5)

        self.btn_atualizar = ttk.Button(acoes_frame, text="Atualizar Lista", command=self.atualizar_lista_remedios)
        self.btn_atualizar.pack(side="left", padx=5)
        
        self.btn_testar_notif = ttk.Button(acoes_frame, text="Testar Notificação", command=self.testar_notificacao_agora)
        self.btn_testar_notif.pack(side="right", padx=5)

    def calcular_previsao(self, estoque, doses_dia):
        """Calcula os dias restantes e a data de término com base no estoque e uso."""
        if doses_dia > 0 and estoque > 0:
            dias_restantes = int(estoque // doses_dia)
            data_fim = datetime.now() + timedelta(days=dias_restantes)
            data_fim_str = data_fim.strftime("%d/%m/%Y")
            dias_str = f"{dias_restantes} dias"
        elif estoque <= 0:
            dias_str = "Acabou!"
            data_fim_str = "N/A"
        else:
            dias_str = "N/A"
            data_fim_str = "N/A"
        return dias_str, data_fim_str

    def atualizar_lista_remedios(self):
        """Busca os dados no banco e atualiza a lista (Treeview)."""
        for item in self.tree.get_children():
            self.tree.delete(item)

        try:
            # --- NOVO: Puxa a 'unidade' do banco ---
            remedios = self.db_cursor.execute("SELECT id, nome, doses_por_dia, estoque_atual, unidade FROM remedios").fetchall()
            for r in remedios:
                remedio_id, nome, doses_dia, estoque, unidade = r
                dias_str, data_fim_str = self.calcular_previsao(estoque, doses_dia)
                
                # Formata a exibição da dose e estoque com a unidade
                dose_display = f"{doses_dia} {unidade}"
                estoque_display = f"{estoque} {unidade}"
                
                self.tree.insert("", "end", iid=remedio_id, values=(nome, dose_display, estoque_display, dias_str, data_fim_str))
        except sqlite3.Error as e:
            messagebox.showerror("Erro de Banco de Dados", f"Erro ao buscar remédios: {e}")

    def cadastrar_remedio(self):
        """Valida os campos e insere um novo remédio no banco."""
        nome = self.entry_nome.get().strip()
        unidade = self.unidade_var.get() # --- NOVO ---
        try:
            doses_dia = int(self.entry_doses_dia.get())
            estoque = int(self.entry_estoque.get())
        except ValueError:
            messagebox.showerror("Erro de Entrada", "Doses por dia e estoque devem ser números inteiros.")
            return

        if not nome or doses_dia <= 0 or estoque < 0:
            messagebox.showerror("Erro de Entrada", "Todos os campos são obrigatórios. Doses/dia deve ser > 0 e estoque >= 0.")
            return

        try:
            # --- NOVO: Insere a 'unidade' no banco ---
            self.db_cursor.execute(
                "INSERT INTO remedios (nome, doses_por_dia, estoque_atual, unidade) VALUES (?, ?, ?, ?)",
                (nome, doses_dia, estoque, unidade)
            )
            remedio_id = self.db_cursor.lastrowid

            if estoque > 0:
                self.db_cursor.execute(
                    "INSERT INTO historico_estoque (remedio_id, quantidade_adicionada, data_adicao) VALUES (?, ?, ?)",
                    (remedio_id, estoque, datetime.now())
                )
            
            self.db_conn.commit()
            messagebox.showinfo("Sucesso", f"Remédio '{nome}' cadastrado com sucesso.")
            
            self.entry_nome.delete(0, "end")
            self.entry_doses_dia.delete(0, "end")
            self.entry_estoque.delete(0, "end")
            self.unidade_var.set("comprimido") # Reseta a unidade
            
            self.atualizar_lista_remedios()

        except sqlite3.IntegrityError:
            messagebox.showerror("Erro", f"O remédio '{nome}' já está cadastrado.")
        except sqlite3.Error as e:
            messagebox.showerror("Erro de Banco de Dados", f"Erro ao cadastrar: {e}")

    def get_remedio_id_selecionado(self):
        """Retorna o ID (do banco) do remédio selecionado na lista."""
        item_selecionado = self.tree.focus()
        if not item_selecionado:
            messagebox.showerror("Nenhuma Seleção", "Por favor, selecione um remédio na lista primeiro.")
            return None
        return int(item_selecionado)

    def adicionar_estoque(self):
        """Adiciona uma nova quantidade ao estoque de um remédio selecionado."""
        remedio_id = self.get_remedio_id_selecionado()
        if remedio_id is None:
            return

        # --- NOVO: Busca a unidade para mostrar no pop-up ---
        valores = self.tree.item(remedio_id, 'values')
        nome_remedio = valores[0]
        estoque_atual_str = valores[2] # Ex: "10 comprimido"
        
        try:
            # Parseia o valor do estoque e a unidade
            estoque_val, unidade = estoque_atual_str.split()
            estoque_val = int(estoque_val)
        except Exception:
            messagebox.showerror("Erro", "Não foi possível ler o estoque atual do remédio selecionado.")
            return

        try:
            prompt = f"Remédio: {nome_remedio}\nEstoque Atual: {estoque_val} {unidade}\n\nQuanto deseja ADICIONAR ({unidade})?"
            quantidade_str = simpledialog.askstring("Adicionar Estoque", prompt)
            
            if quantidade_str is None: return
            
            quantidade = int(quantidade_str)
            if quantidade <= 0:
                messagebox.showerror("Erro", "A quantidade deve ser um número positivo.")
                return
        except (ValueError, TypeError):
            messagebox.showerror("Erro", "Valor inválido.")
            return

        try:
            self.db_cursor.execute(
                "UPDATE remedios SET estoque_atual = estoque_atual + ? WHERE id = ?",
                (quantidade, remedio_id)
            )
            self.db_cursor.execute(
                "INSERT INTO historico_estoque (remedio_id, quantidade_adicionada, data_adicao) VALUES (?, ?, ?)",
                (remedio_id, quantidade, datetime.now())
            )
            self.db_conn.commit()
            self.atualizar_lista_remedios()
        except sqlite3.Error as e:
            messagebox.showerror("Erro de Banco de Dados", f"Erro ao adicionar estoque: {e}")

    def modificar_estoque(self):
        """Modifica o estoque de um remédio para um valor exato."""
        remedio_id = self.get_remedio_id_selecionado()
        if remedio_id is None:
            return

        # --- NOVO: Busca a unidade para mostrar no pop-up ---
        valores = self.tree.item(remedio_id, 'values')
        estoque_atual_str = valores[2] # Ex: "10 comprimido"
        try:
            _, unidade = estoque_atual_str.split()
        except Exception:
            unidade = "" # Fallback

        try:
            prompt = f"Qual o NOVO valor TOTAL do estoque ({unidade})?"
            quantidade_str = simpledialog.askstring("Modificar Estoque", prompt)
            
            if quantidade_str is None: return
            
            quantidade = int(quantidade_str)
            if quantidade < 0:
                messagebox.showerror("Erro", "O estoque não pode ser negativo.")
                return
        except (ValueError, TypeError):
            messagebox.showerror("Erro", "Valor inválido.")
            return

        try:
            self.db_cursor.execute(
                "UPDATE remedios SET estoque_atual = ? WHERE id = ?",
                (quantidade, remedio_id)
            )
            self.db_conn.commit()
            self.atualizar_lista_remedios()
        except sqlite3.Error as e:
            messagebox.showerror("Erro de Banco de Dados", f"Erro ao modificar estoque: {e}")

    def remover_remedio_selecionado(self):
        """Remove um remédio selecionado do banco de dados."""
        remedio_id = self.get_remedio_id_selecionado()
        if remedio_id is None:
            return

        nome_remedio = self.tree.item(remedio_id, 'values')[0]
        
        if not messagebox.askyesno("Confirmar Remoção", f"Tem certeza que deseja remover '{nome_remedio}'?\n\nTodo o seu histórico de estoque também será apagado."):
            return

        try:
            self.db_cursor.execute("DELETE FROM remedios WHERE id = ?", (remedio_id,))
            self.db_conn.commit()
            
            messagebox.showinfo("Sucesso", f"'{nome_remedio}' foi removido.")
            self.atualizar_lista_remedios()
            
        except sqlite3.Error as e:
            messagebox.showerror("Erro de Banco de Dados", f"Erro ao remover remédio: {e}")

    # --- Lógica de Notificação e Threads ---

    def _verificar_estoque_notificacao(self):
        """Verifica o estoque e agenda notificações na thread principal."""
        if not NOTIFIER_AVAILABLE:
            return

        print("Executando verificação de estoque (Notificação)...")
        
        conn_thread = None
        try:
            conn_thread = sqlite3.connect(self.db_name)
            cursor_thread = conn_thread.cursor()
            
            # --- NOVO: Puxa a 'unidade' do banco ---
            remedios = cursor_thread.execute("SELECT nome, doses_por_dia, estoque_atual, unidade FROM remedios").fetchall()
            
            LIMITE_DIAS = 5
            
            for nome, doses_dia, estoque, unidade in remedios:
                if doses_dia > 0 and estoque > 0:
                    dias_restantes = int(estoque // doses_dia)
                    if dias_restantes <= LIMITE_DIAS:
                        print(f"Estoque baixo detectado para: {nome}")
                        
                        # Pluraliza "comprimido" se necessário
                        unidade_str = "comprimidos" if unidade == "comprimido" and estoque != 1 else unidade
                        
                        titulo = "Alerta de Estoque Baixo!"
                        mensagem = f"O remédio '{nome}' está acabando. Restam apenas {estoque} {unidade_str} ({dias_restantes} dias)."
                        
                        self.root.after(0, self.agendar_notificacao_main_thread, titulo, mensagem)
                        
            print("Verificação de notificações concluída.")

        except sqlite3.Error as e:
            print(f"Erro na thread de notificação (SQLite): {e}")
        except Exception as e:
            print(f"Erro inesperado na thread de notificação: {e}")
        finally:
            if conn_thread:
                conn_thread.close()

    def _loop_notificacao(self):
        """Loop infinito que roda na thread de fundo."""
        time.sleep(10)
        
        while True:
            self._verificar_estoque_notificacao()
            time.sleep(4 * 3600)

    def iniciar_verificador_notificacoes(self):
        """Inicia a thread de notificação em segundo plano."""
        if not NOTIFIER_AVAILABLE:
            print("Notificações desabilitadas. Thread de verificação não iniciada.")
            return
            
        self.notification_thread = threading.Thread(target=self._loop_notificacao)
        self.notification_thread.daemon = True
        self.notification_thread.start()
        print("Thread de notificação iniciada.")

    def agendar_notificacao_main_thread(self, titulo, mensagem):
        """Função segura para ser chamada pela thread de fundo."""
        if not (NOTIFIER_AVAILABLE and self.toaster):
            return

        try:
            icon_path = resource_path("cardiogram.ico")
            
            self.toaster.show_toast(
                title=titulo,
                msg=mensagem,
                duration=10,
                icon_path=icon_path,
                threaded=True
            )
            print(f"Notificação agendada exibida: {titulo}")
        except Exception as e:
            print(f"Erro ao tentar MOSTRAR notificação: {e}")

    def testar_notificacao_agora(self):
        """Força uma verificação de estoque (para testes)."""
        if not NOTIFIER_AVAILABLE:
            messagebox.showwarning("Notificações Desabilitadas",
                                 "A biblioteca 'win10toast' não foi encontrada. As notificações estão desativadas.")
            return

        messagebox.showinfo("Teste de Notificação", 
                            "Verificação de estoque em segundo plano iniciada.\n\nSe houver remédios com 5 dias ou menos de estoque, você receberá uma notificação em alguns segundos.")
        
        threading.Thread(target=self._verificar_estoque_notificacao).start()

    # --- Funções do Ícone da Bandeja (System Tray) ---

    def setup_tray_icon(self):
        """Configura o ícone na bandeja do sistema."""
        try:
            image_path = resource_path("cardiogram.png")
            image = Image.open(image_path)
            
            menu = Menu(
                MenuItem('Abrir Gerenciador', self.on_menu_mostrar, default=True),
                MenuItem('Sair', self.on_menu_sair)
            )
            
            self.tray_icon = TrayIcon("GerenciadorRemedios", image, "Gerenciador de Remédios", menu)
            
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
            
        except Exception as e:
            print(f"Erro ao criar ícone da bandeja: {e}")
            global TRAY_AVAILABLE
            TRAY_AVAILABLE = False
            self.root.protocol("WM_DELETE_WINDOW", self.sair_app)

    def on_menu_mostrar(self):
        """Chamado pela thread do pystray para agendar 'mostrar_janela'."""
        self.root.after(0, self.mostrar_janela)

    def on_menu_sair(self):
        """Chamado pela thread do pystray para agendar 'sair_app'."""
        self.root.after(0, self.sair_app)

    def esconder_janela(self):
        """Esconde a janela principal (minimiza para a bandeja)."""
        self.root.withdraw()

    def mostrar_janela(self):
        """Mostra a janela."""
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def sair_app(self):
        """Fecha o aplicativo completamente (de forma segura)."""
        print("Fechando aplicativo...")
        
        if self.tray_icon and TRAY_AVAILABLE:
            self.tray_icon.stop()
            print("Ícone da bandeja parado.")
        
        if self.db_conn:
            self.db_conn.close()
            print("Conexão DB fechada.")
            
        print("Agendando destruição da janela em 100ms...")
        self.root.after(100, self.root.destroy)


if __name__ == "__main__":
    root = tk.Tk()
    
    icon_image = None
    try:
        png_path = resource_path("cardiogram.png")
        pil_image = Image.open(png_path)
        icon_image = ImageTk.PhotoImage(pil_image)
        root.iconphoto(True, icon_image)
    except Exception as e:
        print(f"Não foi possível carregar o ícone .png da janela: {e}")
        try:
            icon_path = resource_path("cardiogram.ico")
            root.iconbitmap(icon_path)
        except Exception as e2:
            print(f"Também falhou ao carregar o .ico: {e2}")
            
    app = App(root)
    root.mainloop()