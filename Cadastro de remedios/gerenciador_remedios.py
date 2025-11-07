import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import sqlite3
import os
from datetime import datetime, timedelta
import threading
import time
import sys
# NOVAS IMPORTAÇÕES
try:
    import pystray
    from PIL import Image
    SYSTEM_TRAY_AVAILABLE = True
except ImportError:
    print("Bibliotecas 'pystray' ou 'Pillow' não encontradas.")
    print("Para o ícone na bandeja, instale com: pip install pystray pillow")
    SYSTEM_TRAY_AVAILABLE = False
    pystray = None
    Image = None

def resource_path(relative_path):
    """ Retorna o caminho absoluto para o recurso, funcionando em dev e no PyInstaller """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(os.path.dirname(__file__))
    return os.path.join(base_path, relative_path)

DB_PATH = os.path.join(os.path.expanduser("~"), "remedios.db")
print(f"Usando banco de dados em: {DB_PATH}")

try:
    from win10toast import ToastNotifier
    NOTIFIER_AVAILABLE = True
except ImportError:
    print("Biblioteca 'win10toast' não encontrada.")
    NOTIFIER_AVAILABLE = False
    ToastNotifier = None

class App:
    """Classe principal da aplicação Gerenciador de Remédios."""
    
    def __init__(self, root_window):
        """Inicializa a aplicação."""
        global NOTIFIER_AVAILABLE 
        
        self.root = root_window
        self.root.title("Gerenciador de Remédios")
        self.root.geometry("800x600")
        
        # --- Lógica do Ícone na Bandeja ---
        self.icon = None # Objeto do pystray
        self.icon_image = None # Objeto da imagem PIL
        if SYSTEM_TRAY_AVAILABLE:
            try:
                # Carrega a imagem para o ícone (pystray usa PIL, não Tkinter)
                icon_path = resource_path('cardiogram.png')
                self.icon_image = Image.open(icon_path)
            except Exception as e:
                print(f"Não foi possível carregar a imagem do ícone para a bandeja: {e}")
                self.icon_image = None
        # -----------------------------------

        self.db_name = DB_PATH
        self.db_conn = None
        self.db_cursor = None
        
        try:
            self._init_db()
        except sqlite3.Error as e:
            messagebox.showerror("Erro de Banco de Dados", f"Erro fatal ao conectar ou criar tabelas: {e}")
            self.root.destroy()
            return
            
        self._setup_ui()
        self.atualizar_lista_remedios()
        
        self.toaster = None
        if NOTIFIER_AVAILABLE:
            try:
                self.toaster = ToastNotifier()
                print("Notificador (win10toast) inicializado com sucesso.")
            except Exception as e:
                print(f"Falha ao inicializar o ToastNotifier: {e}")
                NOTIFIER_AVAILABLE = False
        
        self.iniciar_verificador_notificacoes()
        
        # --- Lógica de Inicialização ---
        # Se o script foi chamado com --minimized (pelo Iniciar do Windows),
        # esconde a janela principal. Senão, mostra.
        if "--minimized" in sys.argv:
            self.root.withdraw() # Esconde a janela
        else:
            self.root.deiconify() # Mostra a janela

        # Inicia o ícone da bandeja em uma thread separada
        if SYSTEM_TRAY_AVAILABLE and self.icon_image:
            self._setup_system_tray()
            
    def _init_db(self):
        """Inicializa a conexão com o banco de dados e cria as tabelas se não existirem."""
        self.db_conn = sqlite3.connect(self.db_name)
        self.db_cursor = self.db_conn.cursor()
        self.db_cursor.execute("PRAGMA foreign_keys = ON;")
        
        self.db_cursor.execute("""
            CREATE TABLE IF NOT EXISTS remedios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                doses_por_dia REAL NOT NULL,
                estoque_atual REAL NOT NULL,
                data_cadastro TEXT NOT NULL,
                UNIQUE(nome) 
            )
        """)
        
        self.db_cursor.execute("""
            CREATE TABLE IF NOT EXISTS historico_estoque (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                remedio_id INTEGER NOT NULL,
                quantidade_adicionada REAL NOT NULL,
                data_adicao TEXT NOT NULL,
                FOREIGN KEY (remedio_id) REFERENCES remedios (id) ON DELETE CASCADE
            )
        """)
        self.db_conn.commit()

    def _setup_ui(self):
        """Configura a interface gráfica (widgets)."""
        frame_cadastro = ttk.LabelFrame(self.root, text="Cadastrar Novo Remédio", padding=10)
        frame_cadastro.pack(fill="x", padx=10, pady=10)
        
        ttk.Label(frame_cadastro, text="Nome:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.entry_nome = ttk.Entry(frame_cadastro)
        self.entry_nome.grid(row=0, column=1, columnspan=3, padx=5, pady=5, sticky="ew") 
        
        btn_cadastrar = ttk.Button(frame_cadastro, text="Cadastrar", command=self.cadastrar_remedio)
        btn_cadastrar.grid(row=0, column=4, rowspan=2, padx=10, pady=5, sticky="ns")

        ttk.Label(frame_cadastro, text="Doses por Dia:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.entry_doses_dia = ttk.Entry(frame_cadastro, width=15)
        self.entry_doses_dia.grid(row=1, column=1, padx=5, pady=5, sticky="w")
        
        ttk.Label(frame_cadastro, text="Estoque Inicial:").grid(row=1, column=2, padx=5, pady=5, sticky="w")
        self.entry_estoque_inicial = ttk.Entry(frame_cadastro, width=15)
        self.entry_estoque_inicial.grid(row=1, column=3, padx=5, pady=5, sticky="w")
        
        frame_cadastro.columnconfigure(1, weight=1)

        frame_lista = ttk.LabelFrame(self.root, text="Meus Remédios", padding=10)
        frame_lista.pack(fill="both", expand=True, padx=10, pady=5)
        
        colunas = ('nome', 'doses_dia', 'estoque', 'previsao_dias', 'previsao_data')
        self.lista_remedios = ttk.Treeview(frame_lista, columns=colunas, show='headings')
        
        headings = {
            'nome': 'Remédio', 'doses_dia': 'Doses/Dia', 'estoque': 'Estoque Atual',
            'previsao_dias': 'Dias Restantes', 'previsao_data': 'Data Prev. Fim'
        }
        for col, text in headings.items():
            self.lista_remedios.heading(col, text=text)

        self.lista_remedios.column('nome', width=250)
        self.lista_remedios.column('doses_dia', width=80, anchor="center")
        self.lista_remedios.column('estoque', width=100, anchor="center")
        self.lista_remedios.column('previsao_dias', width=100, anchor="center")
        self.lista_remedios.column('previsao_data', width=120, anchor="center")
        
        scrollbar = ttk.Scrollbar(frame_lista, orient="vertical", command=self.lista_remedios.yview)
        self.lista_remedios.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.lista_remedios.pack(fill="both", expand=True)
        
        frame_acoes = ttk.Frame(self.root, padding=10)
        frame_acoes.pack(fill="x")
        
        botoes_acoes = {
            "Adicionar Estoque": self.adicionar_estoque_selecionado,
            "Modificar Estoque": self.modificar_estoque_selecionado,
            "Remover Remédio": self.remover_remedio_selecionado,
            "Atualizar Lista": self.atualizar_lista_remedios,
            "Testar Notificação": self.testar_notificacao_agora
        }
        
        for texto, comando in botoes_acoes.items():
            padx_val = 10 if texto == "Atualizar Lista" else 5
            ttk.Button(frame_acoes, text=texto, command=comando).pack(side="left", padx=padx_val)

    # --- Funções da Lógica da Bandeja (System Tray) ---

    def _setup_system_tray(self):
        """Configura e inicia o ícone na bandeja do sistema."""
        menu = (
            pystray.MenuItem('Abrir Gerenciador', self.show_window, default=True),
            pystray.MenuItem('Sair', self.quit_app)
        )
        self.icon = pystray.Icon("Gerenciador de Remédios", self.icon_image, "Gerenciador de Remédios", menu)
        
        # Roda o ícone em uma thread separada para não bloquear o Tkinter
        threading.Thread(target=self.icon.run, daemon=True).start()

    def show_window(self):
        """Mostra a janela principal (chamado pelo ícone da bandeja)."""
        # Como isso é chamado pela thread do pystray, usamos root.after
        # para pedir à thread do Tkinter para executar a ação.
        self.root.after(0, self.root.deiconify)
        self.root.after(0, self.root.lift) # Traz para frente
        self.root.after(0, self.root.focus_force)

    def hide_window(self):
        """Esconde a janela principal (chamado pelo botão 'X')."""
        self.root.withdraw()
        # Opcional: notificar que o app ainda está rodando
        if self.toaster and NOTIFIER_AVAILABLE:
            self.agendar_notificacao_main_thread(
                "Gerenciador de Remédios",
                "O aplicativo continua rodando em segundo plano.\nClique no ícone na bandeja para abri-lo.",
                duration=5
            )

    def quit_app(self):
        """Fecha a aplicação (chamado pelo menu da bandeja)."""
        # Pede para o pystray parar (fecha a thread dele)
        if self.icon:
            self.icon.stop()
        # Pede para o Tkinter fechar (fecha a thread principal)
        # Usamos root.after para garantir que seja executado na thread do Tkinter.
        self.root.after(0, self._real_quit)

    def _real_quit(self):
        """Ação de fechar real, executada na thread do Tkinter."""
        print("Fechando aplicação...")
        self.root.destroy()

    # --- Funções de Lógica do App ---
    
    def cadastrar_remedio(self):
        """Cadastra um novo remédio no banco de dados."""
        nome = self.entry_nome.get().strip()
        try:
            doses_dia = float(self.entry_doses_dia.get().replace(',', '.'))
            estoque = float(self.entry_estoque_inicial.get().replace(',', '.'))
        except ValueError:
            messagebox.showerror("Erro de Entrada", "Doses por dia e estoque devem ser números.")
            return

        if not nome or doses_dia <= 0 or estoque < 0:
            messagebox.showerror("Erro de Entrada", "Preencha todos os campos corretamente (Doses > 0).")
            return
            
        data_cadastro = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            self.db_cursor.execute("INSERT INTO remedios (nome, doses_por_dia, estoque_atual, data_cadastro) VALUES (?, ?, ?, ?)", (nome, doses_dia, estoque, data_cadastro))
            remedio_id = self.db_cursor.lastrowid
            if estoque > 0: self.logar_estoque(remedio_id, estoque)
            self.db_conn.commit()
            messagebox.showinfo("Sucesso", f"Remédio '{nome}' cadastrado com sucesso!")
            self.entry_nome.delete(0, "end"); self.entry_doses_dia.delete(0, "end"); self.entry_estoque_inicial.delete(0, "end")
            self.atualizar_lista_remedios()
        except sqlite3.IntegrityError:
            messagebox.showerror("Erro", f"O remédio '{nome}' já está cadastrado.")
        except sqlite3.Error as e:
            messagebox.showerror("Erro de Banco de Dados", f"Erro ao cadastrar: {e}")

    def _get_remedio_selecionado(self):
        """Helper para pegar o ID e nome do remédio selecionado."""
        selecionado = self.lista_remedios.focus()
        if not selecionado:
            messagebox.showwarning("Nenhum Remédio", "Por favor, selecione um remédio na lista.")
            return None, None, None
        
        item = self.lista_remedios.item(selecionado)
        remedio_id = item['tags'][0]
        nome_remedio = item['values'][0]
        return selecionado, remedio_id, nome_remedio

    def adicionar_estoque_selecionado(self):
        """Adiciona estoque a um remédio selecionado na lista."""
        _, remedio_id, nome_remedio = self._get_remedio_selecionado()
        if not remedio_id: return

        quantidade_str = simpledialog.askstring("Adicionar Estoque", f"Quanto de '{nome_remedio}' você quer adicionar?", parent=self.root)
        if not quantidade_str: return
            
        try:
            quantidade = float(quantidade_str.replace(',', '.'))
            if quantidade <= 0: raise ValueError
        except ValueError:
            messagebox.showerror("Valor Inválido", "A quantidade deve ser um número positivo.")
            return
            
        try:
            self.db_cursor.execute("UPDATE remedios SET estoque_atual = estoque_atual + ? WHERE id = ?", (quantidade, remedio_id))
            self.logar_estoque(remedio_id, quantidade)
            self.db_conn.commit()
            self.atualizar_lista_remedios()
        except sqlite3.Error as e:
            messagebox.showerror("Erro de Banco de Dados", f"Erro ao adicionar estoque: {e}")

    def modificar_estoque_selecionado(self):
        """Modifica o valor total do estoque de um remédio selecionado."""
        selecionado, remedio_id, nome_remedio = self._get_remedio_selecionado()
        if not remedio_id: return

        item = self.lista_remedios.item(selecionado)
        try: estoque_antigo = float(item['values'][2])
        except (ValueError, TypeError): estoque_antigo = 0.0

        novo_estoque_str = simpledialog.askstring("Modificar Estoque", f"Qual o valor TOTAL do estoque de '{nome_remedio}'?\n(Valor atual: {estoque_antigo})", parent=self.root)
        if not novo_estoque_str: return

        try:
            novo_estoque = float(novo_estoque_str.replace(',', '.'))
            if novo_estoque < 0: raise ValueError
        except ValueError:
            messagebox.showerror("Valor Inválido", "O estoque deve ser um número positivo ou zero.")
            return

        try:
            diferenca = novo_estoque - estoque_antigo
            self.db_cursor.execute("UPDATE remedios SET estoque_atual = ? WHERE id = ?", (novo_estoque, remedio_id))
            if diferenca != 0: self.logar_estoque(remedio_id, diferenca)
            self.db_conn.commit()
            self.atualizar_lista_remedios()
        except sqlite3.Error as e:
            messagebox.showerror("Erro de Banco de Dados", f"Erro ao modificar estoque: {e}")

    def remover_remedio_selecionado(self):
        """Remove um remédio selecionado do banco de dados."""
        _, remedio_id, nome_remedio = self._get_remedio_selecionado()
        if not remedio_id: return

        confirmar = messagebox.askyesno("Confirmar Remoção", f"Tem certeza que deseja remover o remédio '{nome_remedio}'?\n\nTodo o seu histórico também será apagado.", parent=self.root, icon='warning')
        if not confirmar: return

        try:
            self.db_cursor.execute("DELETE FROM remedios WHERE id = ?", (remedio_id,))
            self.db_conn.commit()
            messagebox.showinfo("Sucesso", f"Remédio '{nome_remedio}' removido com sucesso.")
            self.atualizar_lista_remedios()
        except sqlite3.Error as e:
            messagebox.showerror("Erro de Banco de Dados", f"Erro ao remover remédio: {e}")

    def testar_notificacao_agora(self):
        """Força uma verificação de estoque e notificação (para teste)."""
        global NOTIFIER_AVAILABLE 
        if not NOTIFIER_AVAILABLE:
            messagebox.showwarning("Biblioteca Ausente", "A biblioteca 'win10toast' não está instalada.\nInstale com: pip install win10toast")
            return
        
        messagebox.showinfo("Teste Iniciado", "A verificação de notificação foi iniciada em segundo plano.\n\nSe algum remédio estiver com 5 dias ou menos de estoque, você receberá um aviso em alguns segundos.")
        threading.Thread(target=self._verificar_estoque_notificacao, daemon=True).start()

    def logar_estoque(self, remedio_id, quantidade):
        """Registra uma adição de estoque no histórico."""
        data_adicao = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            self.db_cursor.execute("INSERT INTO historico_estoque (remedio_id, quantidade_adicionada, data_adicao) VALUES (?, ?, ?)", (remedio_id, quantidade, data_adicao))
        except sqlite3.Error as e:
            print(f"Erro ao logar estoque: {e}")
            
    def atualizar_lista_remedios(self):
        """Busca os remédios no DB e atualiza a lista (Treeview)."""
        for item in self.lista_remedios.get_children():
            self.lista_remedios.delete(item)
            
        try:
            self.db_cursor.execute("SELECT id, nome, doses_por_dia, estoque_atual FROM remedios")
            remedios = self.db_cursor.fetchall()
            
            for remedio in remedios:
                remedio_id, nome, doses_dia, estoque = remedio
                dias, data_fim = self.calcula_previsao(estoque, doses_dia)
                self.lista_remedios.insert('', 'end', values=(nome, doses_dia, estoque, dias, data_fim), tags=(remedio_id,))
        except sqlite3.Error as e:
            messagebox.showerror("Erro de Banco de Dados", f"Erro ao buscar remédios: {e}")

    def calcula_previsao(self, estoque, doses_dia):
        """Calcula os dias restantes e a data de término."""
        if doses_dia <= 0: return "N/A", "N/A"
        try:
            dias_restantes = int(estoque / doses_dia)
            data_fim = datetime.now() + timedelta(days=dias_restantes)
            return f"{dias_restantes} dias", data_fim.strftime("%d/%m/%Y")
        except Exception:
            return "Erro", "Erro"
            
    def agendar_notificacao_main_thread(self, titulo, mensagem, duration=10):
        """Agenda a exibição da notificação na thread principal (UI)."""
        if not self.toaster:
            print("Notificador não está disponível, exibição pulada.")
            return
        try:
            self.toaster.show_toast(title=titulo, msg=mensagem, duration=duration, icon_path=None, threaded=True)
            print(f"Notificação agendada exibida: {titulo}")
        except Exception as e:
            print(f"Erro ao exibir notificação (self.toaster.show_toast): {e}")

    def _verificar_estoque_notificacao(self):
        """Verifica o estoque e agenda notificações se necessário. Roda em thread separada."""
        global NOTIFIER_AVAILABLE
        if not NOTIFIER_AVAILABLE: return
            
        LIMITE_DIAS = 5 
        conn_thread = None
        try:
            conn_thread = sqlite3.connect(self.db_name)
            conn_thread.execute("PRAGMA foreign_keys = ON;")
            cursor_thread = conn_thread.cursor()
            cursor_thread.execute("SELECT nome, estoque_atual, doses_por_dia FROM remedios")
            remedios = cursor_thread.fetchall()
            
            for nome, estoque, doses_dia in remedios:
                if doses_dia > 0:
                    dias_restantes = int(estoque / doses_dia)
                    if dias_restantes <= LIMITE_DIAS:
                        print(f"Estoque baixo detectado para: {nome}")
                        titulo = "Alerta de Estoque Baixo!"
                        mensagem = f"O remédio '{nome}' está acabando. Restam apenas {dias_restantes} dias ({estoque} unidades)."
                        self.root.after(0, self.agendar_notificacao_main_thread, titulo, mensagem)
                        time.sleep(6) 
        except Exception as e:
            print(f"Erro na thread de notificação: {e}")
        finally:
            if conn_thread: conn_thread.close()

    def _loop_notificacao(self):
        """Loop infinito que roda em segundo plano para verificar o estoque."""
        print("Thread de notificação iniciada.")
        time.sleep(10) 
        while True:
            print("Executando verificação de estoque em segundo plano...")
            self._verificar_estoque_notificacao()
            time.sleep(4 * 3600) 

    def iniciar_verificador_notificacoes(self):
        """Cria e inicia a thread de notificação."""
        if not NOTIFIER_AVAILABLE:
            print("Notificações desabilitadas (win10toast não encontrada).")
            return
        threading.Thread(target=self._loop_notificacao, daemon=True).start()

if __name__ == "__main__":
    root = tk.Tk()
    
    # Esconde a janela imediatamente. O __init__ do App vai decidir se mostra ou não.
    root.withdraw() 
    
    try:
        icon_path = resource_path('cardiogram.png')
        icon = tk.PhotoImage(file=icon_path)
        root.iconphoto(True, icon)
    except tk.TclError:
        print(f"Arquivo de ícone não encontrado em: {icon_path}. Usando ícone padrão.")
    except Exception as e:
        print(f"Não foi possível carregar o ícone: {e}")
    
    app = App(root)
    
    # Sobrescreve o botão 'X' para chamar a função de esconder
    root.protocol("WM_DELETE_WINDOW", app.hide_window)
    
    root.mainloop()