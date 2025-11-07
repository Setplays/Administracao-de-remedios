import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import sqlite3
import os
import sys
from datetime import datetime, timedelta
import threading
import time

# --- Configuração de Caminhos ---
# Determina o caminho "home" do usuário para salvar o banco de dados
# Este é um local seguro onde o programa sempre terá permissão para escrever
DB_PATH = os.path.join(os.path.expanduser("~"), "remedios.db")

# Tenta importar a biblioteca de notificação
try:
    from win10toast import ToastNotifier
    NOTIFIER_AVAILABLE = True
except ImportError:
    print("Biblioteca 'win10toast' não encontrada.")
    print("O programa funcionará, mas sem notificações.")
    print("Para instalar, use: pip install win10toast")
    NOTIFIER_AVAILABLE = False
    ToastNotifier = None  # Garante que a classe não exista se a importação falhar

# Tenta importar bibliotecas para o ícone da bandeja
try:
    from pystray import Icon as TrayIcon, Menu, MenuItem
    from PIL import Image
    TRAY_AVAILABLE = True
except ImportError:
    print("Bibliotecas 'pystray' ou 'Pillow' não encontradas.")
    print("O programa funcionará em modo de janela normal.")
    print("Para instalar, use: pip install pystray pillow")
    TRAY_AVAILABLE = False
# --- Fim das Importações ---


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
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


class App:
    """Classe principal do aplicativo Gerenciador de Remédios."""

    def __init__(self, root):
        self.root = root
        self.db_name = DB_PATH
        self.db_conn = None
        self.db_cursor = None
        self.toaster = None
        
        # --- Configuração Inicial ---
        # Devemos usar a variável global para poder modificá-la no 'except'
        global NOTIFIER_AVAILABLE
        
        self.root.title("Gerenciador de Remédios")
        self.root.geometry("800x600")

        # Tenta inicializar o notificador (win10toast) uma única vez
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

        # Inicia a thread de verificação de notificações
        self.iniciar_verificador_notificacoes()

        # Configura o ícone da bandeja (System Tray)
        self.tray_icon = None
        if TRAY_AVAILABLE:
            self.setup_tray_icon()
            # Intercepta o clique no "X" da janela
            self.root.protocol("WM_DELETE_WINDOW", self.esconder_janela)
        else:
            # Comportamento normal se o Pystray não estiver disponível
            self.root.protocol("WM_DELETE_WINDOW", self.sair_app)
            
        # Verifica se deve iniciar minimizado
        if "--minimized" in sys.argv and TRAY_AVAILABLE:
            print("Iniciando minimizado...")
            self.esconder_janela()
        else:
            self.root.deiconify() # Garante que a janela apareça

    def _init_db(self):
        """Inicializa a conexão com o banco de dados e cria as tabelas se não existirem."""
        try:
            print(f"Usando banco de dados em: {self.db_name}")
            self.db_conn = sqlite3.connect(self.db_name)
            self.db_cursor = self.db_conn.cursor()
            
            # Ativa as chaves estrangeiras (essencial para ON DELETE CASCADE)
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
            self.db_conn.commit()
        except sqlite3.Error as e:
            messagebox.showerror("Erro de Banco de Dados", f"Erro ao conectar ao SQLite: {e}")
            self.root.quit()

    def _setup_ui(self):
        """Cria e organiza os widgets da interface gráfica."""
        
        # --- Frame de Cadastro ---
        cadastro_frame = ttk.LabelFrame(self.root, text="Cadastrar Novo Remédio", padding=(10, 10))
        cadastro_frame.pack(fill="x", padx=10, pady=10)
        cadastro_frame.column_configure(1, weight=1)

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

        # Configuração da Treeview (lista)
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

        # Scrollbar
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
        if doses_dia > 0:
            dias_restantes = int(estoque // doses_dia)
            data_fim = datetime.now() + timedelta(days=dias_restantes)
            data_fim_str = data_fim.strftime("%d/%m/%Y")
            dias_str = f"{dias_restantes} dias"
        else:
            dias_str = "N/A"
            data_fim_str = "N/A"
        return dias_str, data_fim_str

    def atualizar_lista_remedios(self):
        """Busca os dados no banco e atualiza a lista (Treeview)."""
        # Limpa a lista antiga
        for item in self.tree.get_children():
            self.tree.delete(item)

        try:
            remedios = self.db_cursor.execute("SELECT id, nome, doses_por_dia, estoque_atual FROM remedios").fetchall()
            for r in remedios:
                remedio_id, nome, doses_dia, estoque = r
                dias_str, data_fim_str = self.calcular_previsao(estoque, doses_dia)
                
                # Adiciona o item na lista, guardando o ID do banco na tag 'iid'
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
            # Insere o remédio
            self.db_cursor.execute(
                "INSERT INTO remedios (nome, doses_por_dia, estoque_atual) VALUES (?, ?, ?)",
                (nome, doses_dia, estoque)
            )
            remedio_id = self.db_cursor.lastrowid

            # Registra o estoque inicial no histórico
            if estoque > 0:
                self.db_cursor.execute(
                    "INSERT INTO historico_estoque (remedio_id, quantidade_adicionada, data_adicao) VALUES (?, ?, ?)",
                    (remedio_id, estoque, datetime.now())
                )
            
            self.db_conn.commit()
            messagebox.showinfo("Sucesso", f"Remédio '{nome}' cadastrado com sucesso.")
            
            # Limpa os campos
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
        # O 'iid' que definimos ao inserir é o ID do banco
        return int(item_selecionado)

    def adicionar_estoque(self):
        """Adiciona uma nova quantidade ao estoque de um remédio selecionado."""
        remedio_id = self.get_remedio_id_selecionado()
        if remedio_id is None:
            return

        try:
            quantidade_str = simpledialog.askstring("Adicionar Estoque", "Qual a quantidade que deseja ADICIONAR?")
            if quantidade_str is None: return # Usuário cancelou
            
            quantidade = int(quantidade_str)
            if quantidade <= 0:
                messagebox.showerror("Erro", "A quantidade deve ser um número positivo.")
                return
        except (ValueError, TypeError):
            messagebox.showerror("Erro", "Valor inválido.")
            return

        try:
            # Atualiza o estoque na tabela principal
            self.db_cursor.execute(
                "UPDATE remedios SET estoque_atual = estoque_atual + ? WHERE id = ?",
                (quantidade, remedio_id)
            )
            # Registra no histórico
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
            if quantidade_str is None: return # Usuário cancelou
            
            quantidade = int(quantidade_str)
            if quantidade < 0:
                messagebox.showerror("Erro", "O estoque não pode ser negativo.")
                return
        except (ValueError, TypeError):
            messagebox.showerror("Erro", "Valor inválido.")
            return

        try:
            # Atualiza o estoque na tabela principal para o valor exato
            self.db_cursor.execute(
                "UPDATE remedios SET estoque_atual = ? WHERE id = ?",
                (quantidade, remedio_id)
            )
            # Nota: Idealmente, o histórico deveria refletir essa mudança manual,
            # mas para simplicidade, estamos apenas alterando o valor principal.
            self.db_conn.commit()
            self.atualizar_lista_remedios()
        except sqlite3.Error as e:
            messagebox.showerror("Erro de Banco de Dados", f"Erro ao modificar estoque: {e}")

    def remover_remedio_selecionado(self):
        """Remove um remédio selecionado do banco de dados."""
        remedio_id = self.get_remedio_id_selecionado()
        if remedio_id is None:
            return

        # Pega o nome apenas para a mensagem de confirmação
        nome_remedio = self.tree.item(remedio_id, 'values')[0]
        
        if not messagebox.askyesno("Confirmar Remoção", f"Tem certeza que deseja remover '{nome_remedio}'?\n\nTodo o seu histórico de estoque também será apagado."):
            return

        try:
            # Graças ao "ON DELETE CASCADE", o histórico será apagado junto.
            self.db_cursor.execute("DELETE FROM remedios WHERE id = ?", (remedio_id,))
            self.db_conn.commit()
            
            messagebox.showinfo("Sucesso", f"'{nome_remedio}' foi removido.")
            self.atualizar_lista_remedios()
            
        except sqlite3.Error as e:
            messagebox.showerror("Erro de Banco de Dados", f"Erro ao remover remédio: {e}")

    # --- Lógica de Notificação e Threads ---

    def _verificar_estoque_notificacao(self):
        """
        Função executada na thread de fundo.
        Verifica o estoque e agenda notificações na thread principal.
        """
        if not NOTIFIER_AVAILABLE:
            return # Sai silenciosamente se o notificador não estiver disponível

        print("Executando verificação de estoque em segundo plano...")
        
        # --- Conexão de thread separada ---
        # A thread de fundo NÃO PODE usar a conexão da thread principal (self.db_conn)
        conn_thread = None
        try:
            conn_thread = sqlite3.connect(self.db_name)
            cursor_thread = conn_thread.cursor()
            
            remedios = cursor_thread.execute("SELECT nome, doses_por_dia, estoque_atual FROM remedios").fetchall()
            
            LIMITE_DIAS = 5
            
            for nome, doses_dia, estoque in remedios:
                if doses_dia > 0:
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
            if conn_thread:
                conn_thread.close()

    def _loop_notificacao(self):
        """Loop infinito que roda na thread de fundo."""
        # Espera 10 segundos na primeira vez
        time.sleep(10)
        
        while True:
            self._verificar_estoque_notificacao()
            # Espera 4 horas (4 * 60 * 60 segundos)
            time.sleep(4 * 3600) 

    def iniciar_verificador_notificacoes(self):
        """Inicia a thread de notificação em segundo plano."""
        if not NOTIFIER_AVAILABLE:
            print("Notificações desabilitadas. Thread de verificação não iniciada.")
            return
            
        self.notification_thread = threading.Thread(target=self._loop_notificacao)
        self.notification_thread.daemon = True # Permite que o programa feche mesmo se a thread estiver rodando
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
            # --- CORREÇÃO FINAL ---
            # Devemos passar o caminho do ícone para evitar o erro 'pkg_resources'
            icon_path = resource_path("cardiogram.ico")
            
            self.toaster.show_toast(
                title=titulo,
                msg=mensagem,
                duration=10,
                icon_path=icon_path, # Passa o ícone
                threaded=True # NÃO bloqueia a thread principal
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
        
        # Roda a verificação em uma thread separada para não travar a UI
        threading.Thread(target=self._verificar_estoque_notificacao).start()

    # --- Funções do Ícone da Bandeja (System Tray) ---

    def setup_tray_icon(self):
        """Configura o ícone na bandeja do sistema."""
        try:
            image_path = resource_path("cardiogram.png")
            image = Image.open(image_path)
            
            menu = Menu(
                MenuItem('Abrir Gerenciador', self.mostrar_janela, default=True),
                MenuItem('Sair', self.sair_app)
            )
            
            self.tray_icon = TrayIcon("GerenciadorRemedios", image, "Gerenciador de Remédios", menu)
            
            # Inicia o ícone em sua própria thread
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
            
        except Exception as e:
            print(f"Erro ao criar ícone da bandeja: {e}")
            # Desativa a funcionalidade se falhar
            global TRAY_AVAILABLE
            TRAY_AVAILABLE = False
            self.root.protocol("WM_DELETE_WINDOW", self.sair_app) # Volta ao normal

    def esconder_janela(self):
        """Esconde a janela principal e mostra notificação (se disponível)."""
        self.root.withdraw() # Esconde a janela
        
        if NOTIFIER_AVAILABLE and self.toaster:
            try:
                # Mostra um aviso informando que o app continua rodando
                self.toaster.show_toast(
                    "Gerenciador de Remédios",
                    "O aplicativo continua rodando em segundo plano.",
                    duration=5,
                    icon_path=resource_path("cardiogram.ico"),
                    threaded=True
                )
            except Exception as e:
                print(f"Erro ao mostrar notificação de 'esconder': {e}")

    def mostrar_janela(self):
        """Mostra a janela (chamado pelo ícone da bandeja)."""
        self.root.deiconify() # Re-exibe a janela
        self.root.lift()
        self.root.focus_force()

    def sair_app(self):
        """Fecha o aplicativo completamente."""
        print("Fechando aplicativo...")
        if self.tray_icon and TRAY_AVAILABLE:
            self.tray_icon.stop() # Para a thread do ícone
        self.root.quit() # Para o loop principal do tkinter
        self.root.destroy()
        sys.exit()


if __name__ == "__main__":
    root = tk.Tk()
    
    # Tenta definir o ícone da janela
    try:
        icon_path = resource_path("cardiogram.ico")
        root.iconbitmap(icon_path)
    except Exception as e:
        print(f"Não foi possível carregar o ícone da janela: {e}")
        
    app = App(root)
    root.mainloop()