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

        # _init_db() agora também executa a atualização automática de estoque
        self._init_db()
        
        self._setup_ui()
        self.atualizar_lista_remedios()

        # Inicia a thread de notificação (para estoque baixo)
        self.iniciar_verificador_notificacoes()
        
        # Inicia o loop de verificação diária (para débito automático)
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

    def _init_db(self):
        """Inicializa a conexão com o banco de dados e cria as tabelas se não existirem."""
        try:
            print(f"Usando banco de dados em: {self.db_name}")
            # --- CORREÇÃO DE THREADING ---
            # Remove 'check_same_thread=False'. A thread de notificação
            # agora criará sua própria conexão.
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
            
            # Tabela para rastrear a última execução e debitar o estoque
            self.db_cursor.execute("""
            CREATE TABLE IF NOT EXISTS app_info (
                id INTEGER PRIMARY KEY,
                last_run_date TEXT NOT NULL
            )
            """)
            
            self.db_conn.commit()
            
            # Chama a função de atualização de estoque logo após conectar ao DB
            # Esta função usa self.db_cursor, o que é seguro pois estamos na thread principal.
            self._atualizar_estoque_automatico()

        except sqlite3.Error as e:
            messagebox.showerror("Erro de Banco de Dados", f"Erro ao conectar ao SQLite: {e}")
            self.root.quit()

    def _atualizar_estoque_automatico(self, dias_passados=None):
        """
        Debita o estoque dos remédios com base nos dias que se passaram.
        Esta função é segura para ser chamada pela thread principal (GUI).
        """
        try:
            hoje = date.today()
            hoje_str = hoje.strftime('%Y-%m-%d')
            dias_a_debitar = 0
            
            if dias_passados is None:
                # Lógica de Startup: Verifica quantos dias se passaram desde o fechamento
                self.db_cursor.execute("SELECT last_run_date FROM app_info WHERE id = 1")
                resultado = self.db_cursor.fetchone()
                
                if resultado:
                    last_run_date_str = resultado[0]
                    last_run_date = datetime.strptime(last_run_date_str, '%Y-%m-%d').date()
                    dias_a_debitar = (hoje - last_run_date).days
                else:
                    # Primeira execução
                    print("Primeira execução. Configurando data de verificação de estoque.")
                    self.db_cursor.execute("INSERT INTO app_info (id, last_run_date) VALUES (1, ?)", (hoje_str,))
                    self.db_conn.commit()
                    return # Não há o que debitar
            else:
                # Lógica de Runtime (Meia-noite): sabemos que passou N dias
                dias_a_debitar = dias_passados

            
            if dias_a_debitar > 0:
                print(f"Detectado {dias_a_debitar} dia(s) para debitar. Atualizando estoque...")
                
                self.db_cursor.execute("""
                    UPDATE remedios
                    SET estoque_atual = MAX(0, estoque_atual - (doses_por_dia * ?))
                    WHERE doses_por_dia > 0
                """, (dias_a_debitar,))
                
                # Atualiza a data da última execução para hoje
                self.db_cursor.execute("UPDATE app_info SET last_run_date = ? WHERE id = 1", (hoje_str,))
                self.db_conn.commit()
                print(f"Estoque debitado por {dias_a_debitar} dia(s).")
                
                # Retorna True para sabermos que a lista precisa ser atualizada
                return True 
            else:
                print("Verificação automática de estoque: Nenhum dia se passou.")
                return False # Nada mudou

        except sqlite3.Error as e:
            print(f"Erro ao atualizar estoque automático: {e}")
            messagebox.showwarning("Erro de Atualização", f"Não foi possível atualizar o estoque automático: {e}")
            return False

    def _verificar_mudanca_dia(self):
        """
        Chamado pelo loop 'root.after' para verificar se a data mudou (passou da meia-noite)
        enquanto o app estava aberto. Roda na thread principal (GUI).
        """
        try:
            # É seguro usar self.db_cursor pois esta função é chamada via self.root.after()
            self.db_cursor.execute("SELECT last_run_date FROM app_info WHERE id = 1")
            resultado = self.db_cursor.fetchone()
            
            if resultado:
                last_run_date_str = resultado[0]
                last_run_date = datetime.strptime(last_run_date_str, '%Y-%m-%d').date()
                hoje = date.today()
                
                dias_passados = (hoje - last_run_date).days
                
                if dias_passados > 0:
                    print(f"MEIA-NOITE DETECTADA! Passaram {dias_passados} dia(s).")
                    # Chama a função de débito, que também usa self.db_cursor
                    if self._atualizar_estoque_automatico(dias_passados=dias_passados):
                        self.atualizar_lista_remedios() # Atualiza a UI se o estoque mudou
        
        except sqlite3.Error as e:
            print(f"Erro no loop de verificação diária: {e}")
        except Exception as e:
            print(f"Erro inesperado no loop de verificação diária: {e}")
        finally:
            # Reagenda a próxima verificação
            self.iniciar_loop_verificacao_diaria() # Re-agenda

    def iniciar_loop_verificacao_diaria(self):
        """Agenda a próxima verificação de mudança de dia."""
        # Verifica a cada 10 minutos (600000 ms)
        self.root.after(600000, self._verificar_mudanca_dia)
        # print("Próxima verificação de mudança de dia em 10 minutos.") # Log opcional


    def _setup_ui(self):
        """Cria e organiza os widgets da interface gráfica."""
        
        # --- Frame de Cadastro ---
        cadastro_frame = ttk.LabelFrame(self.root, text="Cadastrar Novo Remédio", padding=(10, 10))
        cadastro_frame.pack(fill="x", padx=10, pady=10)
        cadastro_frame.columnconfigure(1, weight=1)

        ttk.Label(cadastro_frame, text="Nome:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        self.entry_nome = ttk.Entry(cadastro_frame, width=40)
        self.entry_nome.grid(row=0, column=1, columnspan=3, padx=5, pady=5, sticky="we")

        ttk.Label(cadastro_frame, text="Doses por Dia:").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        self.entry_doses_dia = ttk.Entry(cadastro_frame, width=10)
        self.entry_doses_dia.grid(row=1, column=1, padx=5, pady=5, sticky="w")

        ttk.Label(cadastro_frame, text="Estoque Inicial:").grid(row=1, column=2, padx=5, pady=5, sticky="e")
        self.entry_estoque = ttk.Entry(cadastro_frame, width=10)
        self.entry_estoque.grid(row=1, column=3, padx=5, pady=5, sticky="w")
        
        self.btn_cadastrar = ttk.Button(cadastro_frame, text="Cadastrar", command=self.cadastrar_remedio)
        self.btn_cadastrar.grid(row=0, column=4, rowspan=2, padx=10, pady=5, ipady=10)


        # --- Frame da Lista de Remédios ---
        lista_frame = ttk.LabelFrame(self.root, text="Meus Remédios", padding=(10, 10))
        lista_frame.pack(fill="both", expand=True, padx=10, pady=5)

        colunas = ("remedio", "doses_dia", "estoque", "dias_restantes", "data_fim")
        self.tree = ttk.Treeview(lista_frame, columns=colunas, show="headings")

        self.tree.heading("remedio", text="Remédio")
        self.tree.heading("doses_dia", text="Doses/Dia")
        self.tree.heading("estoque", text="Estoque Atual")
        self.tree.heading("dias_restantes", text="Dias Restantes")
        self.tree.heading("data_fim", text="Data Prev. Fim")

        self.tree.column("remedio", width=250)
        self.tree.column("doses_dia", width=80, anchor="center")
        self.tree.column("estoque", width=100, anchor="center")
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
            remedios = self.db_cursor.execute("SELECT id, nome, doses_por_dia, estoque_atual FROM remedios").fetchall()
            for r in remedios:
                remedio_id, nome, doses_dia, estoque = r
                dias_str, data_fim_str = self.calcular_previsao(estoque, doses_dia)
                
                self.tree.insert("", "end", iid=remedio_id, values=(nome, doses_dia, estoque, dias_str, data_fim_str))
        except sqlite3.Error as e:
            messagebox.showerror("Erro de Banco de Dados", f"Erro ao buscar remédios: {e}")

    def cadastrar_remedio(self):
        """Valida os campos e insere um novo remédio no banco."""
        nome = self.entry_nome.get().strip()
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
            self.db_cursor.execute(
                "INSERT INTO remedios (nome, doses_por_dia, estoque_atual) VALUES (?, ?, ?)",
                (nome, doses_dia, estoque)
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

        try:
            quantidade_str = simpledialog.askstring("Adicionar Estoque", "Qual a quantidade que deseja ADICIONAR?")
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

        try:
            quantidade_str = simpledialog.askstring("Modificar Estoque", "Qual o NOVO valor TOTAL do estoque?")
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
        """
        Verifica o estoque e agenda notificações na thread principal.
        CORREÇÃO DE THREADING: Esta função agora cria sua própria conexão DB.
        """
        if not NOTIFIER_AVAILABLE:
            return

        print("Executando verificação de estoque (Notificação)...")
        
        # --- CORREÇÃO DE THREADING (SQLITE) ---
        # A thread de fundo DEVE criar sua própria conexão.
        conn_thread = None
        try:
            # 1. Cria uma conexão SÓ para esta thread
            conn_thread = sqlite3.connect(self.db_name)
            cursor_thread = conn_thread.cursor()
            
            # 2. Usa o novo cursor_thread para a consulta
            remedios = cursor_thread.execute("SELECT nome, doses_por_dia, estoque_atual FROM remedios").fetchall()
            
            LIMITE_DIAS = 5
            
            for nome, doses_dia, estoque in remedios:
                if doses_dia > 0 and estoque > 0: # Só notifica se tiver estoque
                    dias_restantes = int(estoque // doses_dia)
                    if dias_restantes <= LIMITE_DIAS:
                        print(f"Estoque baixo detectado para: {nome}")
                        titulo = "Alerta de Estoque Baixo!"
                        mensagem = f"O remédio '{nome}' está acabando. Restam apenas {estoque} unidades ({dias_restantes} dias)."
                        
                        # Agenda a notificação para rodar na thread principal (GUI)
                        self.root.after(0, self.agendar_notificacao_main_thread, titulo, mensagem)
                        
            print("Verificação de notificações concluída.")

        except sqlite3.Error as e:
            print(f"Erro na thread de notificação (SQLite): {e}")
        except Exception as e:
            print(f"Erro inesperado na thread de notificação: {e}")
        finally:
            # 3. Fecha a conexão da thread
            if conn_thread:
                conn_thread.close()

    def _loop_notificacao(self):
        """Loop infinito que roda na thread de fundo."""
        time.sleep(10)
        
        while True:
            self._verificar_estoque_notificacao()
            time.sleep(4 * 3600) # Espera 4 horas

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
        """
        Função segura para ser chamada pela thread de fundo.
        Ela executa o 'show_toast' na thread principal.
        """
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
            
            # --- CORREÇÃO DE THREADING (PYSTRAY) ---
            # O menu do pystray roda em sua própria thread.
            # Não podemos chamar self.sair_app diretamente dele.
            # Criamos funções "intermediárias" (on_menu_*)
            
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

    # --- NOVAS FUNÇÕES (Correção Pystray) ---
    def on_menu_mostrar(self):
        """
        Chamado pela thread do pystray.
        Agenda 'mostrar_janela' para rodar na thread principal (GUI).
        """
        self.root.after(0, self.mostrar_janela)

    def on_menu_sair(self):
        """
        Chamado pela thread do pystray.
        Agenda 'sair_app' para rodar na thread principal (GUI).
        """
        self.root.after(0, self.sair_app)
    # --- Fim das Novas Funções ---

    def esconder_janela(self):
        """Esconde a janela principal (minimiza para a bandeja)."""
        
        # A janela é escondida IMEDIATAMENTE.
        self.root.withdraw() # Esconde a janela
        
        # O código de notificação de "esconder" foi removido
        # pois estava causando atrasos e ícones "fantasma".

    def mostrar_janela(self):
        """
        Mostra a janela.
        Agora é garantido que esta função roda na thread principal.
        """
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def sair_app(self):
        """
        Fecha o aplicativo completamente.
        Agora é garantido que esta função roda na thread principal.
        """
        print("Fechando aplicativo...")
        
        # 1. Para o ícone da bandeja PRIMEIRO.
        if self.tray_icon and TRAY_AVAILABLE:
            self.tray_icon.stop()
            print("Ícone da bandeja parado.")
        
        # 2. Fecha a conexão com o banco de dados.
        if self.db_conn:
            self.db_conn.close()
            print("Conexão DB fechada.")
            
        # 3. Agenda a destruição da janela principal para daqui a 100ms.
        # Isso dá tempo para a thread do ícone da bandeja (pystray)
        # se encerrar de forma limpa, evitando o erro WNDPROC.
        print("Agendando destruição da janela em 100ms...")
        self.root.after(100, self.root.destroy)


if __name__ == "__main__":
    root = tk.Tk()
    
    # CORREÇÃO: Carregar ícone usando PIL/ImageTk (mais robusto)
    icon_image = None # Garante que a referência seja mantida
    try:
        # Tenta carregar o .png (preferido)
        png_path = resource_path("cardiogram.png")
        pil_image = Image.open(png_path)
        icon_image = ImageTk.PhotoImage(pil_image)
        root.iconphoto(True, icon_image)
    except Exception as e:
        print(f"Não foi possível carregar o ícone .png da janela: {e}")
        try:
            # Tenta carregar o .ico como fallback
            icon_path = resource_path("cardiogram.ico")
            root.iconbitmap(icon_path)
        except Exception as e2:
            print(f"Também falhou ao carregar o .ico: {e2}")
            
    app = App(root)
    root.mainloop()