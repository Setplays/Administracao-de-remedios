import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import sqlite3
import os
from datetime import datetime, timedelta
import threading
import time
import sys # Importado para ler argumentos de linha de comando

# Tenta importar a biblioteca de notificação
try:
    from win10toast import ToastNotifier
    NOTIFIER_AVAILABLE = True
except ImportError:
    print("Biblioteca 'win10toast' não encontrada.")
    print("Para receber notificações do Windows, instale com: pip install win10toast")
    NOTIFIER_AVAILABLE = False
    ToastNotifier = None # Define como None para verificação

class App:
    """Classe principal da aplicação Gerenciador de Remédios."""
    
    def __init__(self, root_window):
        """Inicializa a aplicação."""
        # CORREÇÃO UnboundLocalError:
        # Precisamos dizer a esta função que estamos usando a variável GLOBAL
        global NOTIFIER_AVAILABLE 
        
        self.root = root_window
        self.root.title("Gerenciador de Remédios")
        self.root.geometry("800x600")
        
        # Define o nome do arquivo do banco de dados
        self.db_name = "remedios.db"
        
        # Conexão principal com o banco de dados (usada pela thread principal)
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
        
        # --- CORREÇÃO BUG WNDPROC/WPARAM ---
        # Inicializa o notificador UMA VEZ na thread principal.
        self.toaster = None
        if NOTIFIER_AVAILABLE:
            try:
                # Criamos o objeto aqui e o reutilizamos para sempre
                self.toaster = ToastNotifier()
                print("Notificador (win10toast) inicializado com sucesso.")
            except Exception as e:
                # Lida com casos onde a inicialização falha (ex: Windows Server)
                print(f"Falha ao inicializar o ToastNotifier: {e}")
                NOTIFIER_AVAILABLE = False # Aqui é onde a variável global é modificada
        # --- FIM DA CORREÇÃO ---
        
        # Inicia o verificador de notificações em segundo plano
        self.iniciar_verificador_notificacoes()
        
        # Verifica se deve iniciar minimizado
        if "--minimized" in sys.argv:
            self.root.iconify() # Minimiza para a barra de tarefas
            
    def _init_db(self):
        """Inicializa a conexão com o banco de dados e cria as tabelas se não existirem."""
        
        # Se o arquivo não existir, o connect() o criará
        self.db_conn = sqlite3.connect(self.db_name)
        self.db_cursor = self.db_conn.cursor()
        
        # Habilita suporte a chaves estrangeiras (importante para ON DELETE CASCADE)
        self.db_cursor.execute("PRAGMA foreign_keys = ON;")
        
        # Tabela de remédios
        # SINTAXE CORRIGIDA: Movido 'UNIQUE(nome)' para o final para maior compatibilidade
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
        
        # Tabela para histórico de adição de estoque
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
        
        # --- Frame de Cadastro ---
        frame_cadastro = ttk.LabelFrame(self.root, text="Cadastrar Novo Remédio", padding=10)
        frame_cadastro.pack(fill="x", padx=10, pady=10)
        
        # Linha 0
        ttk.Label(frame_cadastro, text="Nome:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.entry_nome = ttk.Entry(frame_cadastro)
        # CORREÇÃO DE LAYOUT: columnspan=3 para o nome ocupar o espaço
        self.entry_nome.grid(row=0, column=1, columnspan=3, padx=5, pady=5, sticky="ew") 
        
        # CORREÇÃO DE LAYOUT: Botão movido para a coluna 4
        btn_cadastrar = ttk.Button(frame_cadastro, text="Cadastrar", command=self.cadastrar_remedio)
        btn_cadastrar.grid(row=0, column=4, rowspan=2, padx=10, pady=5, sticky="ns")

        # Linha 1
        ttk.Label(frame_cadastro, text="Doses por Dia:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.entry_doses_dia = ttk.Entry(frame_cadastro, width=15)
        self.entry_doses_dia.grid(row=1, column=1, padx=5, pady=5, sticky="w")
        
        # CORREÇÃO DE LAYOUT: Posição correta (coluna 2)
        ttk.Label(frame_cadastro, text="Estoque Inicial:").grid(row=1, column=2, padx=5, pady=5, sticky="w")
        self.entry_estoque_inicial = ttk.Entry(frame_cadastro, width=15)
        self.entry_estoque_inicial.grid(row=1, column=3, padx=5, pady=5, sticky="w")
        
        # Configuração para a coluna do nome esticar
        frame_cadastro.columnconfigure(1, weight=1)

        # --- Frame da Lista de Remédios ---
        frame_lista = ttk.LabelFrame(self.root, text="Meus Remédios", padding=10)
        frame_lista.pack(fill="both", expand=True, padx=10, pady=5)
        
        colunas = ('nome', 'doses_dia', 'estoque', 'previsao_dias', 'previsao_data')
        self.lista_remedios = ttk.Treeview(frame_lista, columns=colunas, show='headings')
        
        self.lista_remedios.heading('nome', text='Remédio')
        self.lista_remedios.heading('doses_dia', text='Doses/Dia')
        self.lista_remedios.heading('estoque', text='Estoque Atual')
        self.lista_remedios.heading('previsao_dias', text='Dias Restantes')
        self.lista_remedios.heading('previsao_data', text='Data Prev. Fim')
        
        self.lista_remedios.column('nome', width=250)
        self.lista_remedios.column('doses_dia', width=80, anchor="center")
        self.lista_remedios.column('estoque', width=100, anchor="center")
        self.lista_remedios.column('previsao_dias', width=100, anchor="center")
        self.lista_remedios.column('previsao_data', width=120, anchor="center")
        
        # Scrollbar
        scrollbar = ttk.Scrollbar(frame_lista, orient="vertical", command=self.lista_remedios.yview)
        self.lista_remedios.configure(yscrollcommand=scrollbar.set)
        
        scrollbar.pack(side="right", fill="y")
        self.lista_remedios.pack(fill="both", expand=True)
        
        # --- Frame de Ações ---
        frame_acoes = ttk.Frame(self.root, padding=10)
        frame_acoes.pack(fill="x")
        
        btn_add_estoque = ttk.Button(frame_acoes, text="Adicionar Estoque", command=self.adicionar_estoque_selecionado)
        btn_add_estoque.pack(side="left", padx=5)
        
        btn_mod_estoque = ttk.Button(frame_acoes, text="Modificar Estoque", command=self.modificar_estoque_selecionado)
        btn_mod_estoque.pack(side="left", padx=5)
        
        # BOTÃO DE REMOVER
        btn_remover_remedio = ttk.Button(frame_acoes, text="Remover Remédio", command=self.remover_remedio_selecionado)
        btn_remover_remedio.pack(side="left", padx=5)
        
        # Botão de Atualizar (caso necessário)
        btn_atualizar_lista = ttk.Button(frame_acoes, text="Atualizar Lista", command=self.atualizar_lista_remedios)
        btn_atualizar_lista.pack(side="left", padx=10)
        
        btn_testar_notificacao = ttk.Button(frame_acoes, text="Testar Notificação", command=self.testar_notificacao_agora)
        btn_testar_notificacao.pack(side="left", padx=5)

    # --- Funções de Lógica ---
    
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
            self.db_cursor.execute("""
                INSERT INTO remedios (nome, doses_por_dia, estoque_atual, data_cadastro)
                VALUES (?, ?, ?, ?)
            """, (nome, doses_dia, estoque, data_cadastro))
            
            # Pega o ID do remédio que acabamos de inserir
            remedio_id = self.db_cursor.lastrowid
            
            # Loga a adição inicial no histórico
            if estoque > 0:
                self.logar_estoque(remedio_id, estoque)
            
            self.db_conn.commit()
            
            messagebox.showinfo("Sucesso", f"Remédio '{nome}' cadastrado com sucesso!")
            
            # Limpa os campos de entrada
            self.entry_nome.delete(0, "end")
            self.entry_doses_dia.delete(0, "end")
            self.entry_estoque_inicial.delete(0, "end")
            
            self.atualizar_lista_remedios()
            
        except sqlite3.IntegrityError:
            messagebox.showerror("Erro", f"O remédio '{nome}' já está cadastrado.")
        except sqlite3.Error as e:
            messagebox.showerror("Erro de Banco de Dados", f"Erro ao cadastrar: {e}")

    def adicionar_estoque_selecionado(self):
        """Adiciona estoque a um remédio selecionado na lista."""
        selecionado = self.lista_remedios.focus()
        if not selecionado:
            messagebox.showwarning("Nenhum Remédio", "Por favor, selecione um remédio na lista.")
            return
            
        # O item 'selecionado' é o ID interno do Treeview (I001, I002, etc)
        # Precisamos pegar o ID real do banco de dados, que armazenamos
        remedio_id = self.lista_remedios.item(selecionado)['tags'][0]
        nome_remedio = self.lista_remedios.item(selecionado)['values'][0]

        quantidade_str = simpledialog.askstring("Adicionar Estoque", 
                                                f"Quanto de '{nome_remedio}' você quer adicionar?",
                                                parent=self.root)
        
        if not quantidade_str:
            return
            
        try:
            quantidade = float(quantidade_str.replace(',', '.'))
            if quantidade <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Valor Inválido", "A quantidade deve ser um número positivo.")
            return
            
        try:
            # Atualiza o estoque na tabela principal
            self.db_cursor.execute("""
                UPDATE remedios
                SET estoque_atual = estoque_atual + ?
                WHERE id = ?
            """, (quantidade, remedio_id))
            
            # Loga no histórico
            self.logar_estoque(remedio_id, quantidade)
            
            self.db_conn.commit()
            self.atualizar_lista_remedios()
            
        except sqlite3.Error as e:
            messagebox.showerror("Erro de Banco de Dados", f"Erro ao adicionar estoque: {e}")

    def modificar_estoque_selecionado(self):
        """Modifica o valor total do estoque de um remédio selecionado."""
        selecionado = self.lista_remedios.focus()
        if not selecionado:
            messagebox.showwarning("Nenhum Remédio", "Por favor, selecione um remédio na lista.")
            return

        remedio_id = self.lista_remedios.item(selecionado)['tags'][0]
        item = self.lista_remedios.item(selecionado)
        nome_remedio = item['values'][0]
        
        # Trata caso onde estoque pode ser 'N/A' ou texto
        try:
            estoque_antigo = float(item['values'][2])
        except (ValueError, TypeError):
            estoque_antigo = 0.0

        novo_estoque_str = simpledialog.askstring("Modificar Estoque",
                                                  f"Qual o valor TOTAL do estoque de '{nome_remedio}'?\n(Valor atual: {estoque_antigo})",
                                                  parent=self.root)

        if not novo_estoque_str:
            return

        try:
            novo_estoque = float(novo_estoque_str.replace(',', '.'))
            if novo_estoque < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Valor Inválido", "O estoque deve ser um número positivo ou zero.")
            return

        try:
            # Calcula a diferença para logar
            diferenca = novo_estoque - estoque_antigo
            
            # Atualiza o estoque na tabela principal
            self.db_cursor.execute("UPDATE remedios SET estoque_atual = ? WHERE id = ?", (novo_estoque, remedio_id))
            
            # Loga a modificação no histórico
            # Se a diferença for 0, não loga
            if diferenca != 0:
                self.logar_estoque(remedio_id, diferenca) # Loga a diferença (positiva ou negativa)
            
            self.db_conn.commit()
            self.atualizar_lista_remedios()
            
        except sqlite3.Error as e:
            messagebox.showerror("Erro de Banco de Dados", f"Erro ao modificar estoque: {e}")

    def remover_remedio_selecionado(self):
        """Remove um remédio selecionado do banco de dados."""
        selecionado = self.lista_remedios.focus()
        if not selecionado:
            messagebox.showwarning("Nenhum Remédio", "Por favor, selecione um remédio na lista.")
            return

        # Pega o ID e o nome para a mensagem de confirmação
        remedio_id = self.lista_remedios.item(selecionado)['tags'][0]
        nome_remedio = self.lista_remedios.item(selecionado)['values'][0]

        # Pede confirmação
        confirmar = messagebox.askyesno("Confirmar Remoção",
                                        f"Tem certeza que deseja remover o remédio '{nome_remedio}'?\n\nTodo o seu histórico também será apagado.",
                                        parent=self.root,
                                        icon='warning')

        if not confirmar:
            return

        try:
            # Executa o DELETE. O 'ON DELETE CASCADE' cuidará do histórico.
            self.db_cursor.execute("DELETE FROM remedios WHERE id = ?", (remedio_id,))
            self.db_conn.commit()
            
            messagebox.showinfo("Sucesso", f"Remédio '{nome_remedio}' removido com sucesso.")
            self.atualizar_lista_remedios()
            
        except sqlite3.Error as e:
            messagebox.showerror("Erro de Banco de Dados", f"Erro ao remover remédio: {e}")

    def testar_notificacao_agora(self):
        """Força uma verificação de estoque e notificação (para teste)."""
        global NOTIFIER_AVAILABLE # Precisamos ler a variável global
        if not NOTIFIER_AVAILABLE:
            messagebox.showwarning("Biblioteca Ausente", 
                                   "A biblioteca 'win10toast' não está instalada.\nInstale com: pip install win10toast")
            return
        
        messagebox.showinfo("Teste Iniciado", "A verificação de notificação foi iniciada em segundo plano.\n\nSe algum remédio estiver com 5 dias ou menos de estoque, você receberá um aviso em alguns segundos.")
        
        # Inicia a verificação em uma thread separada para não travar a UI
        threading.Thread(target=self._verificar_estoque_notificacao, daemon=True).start()

    def logar_estoque(self, remedio_id, quantidade):
        """Registra uma adição de estoque no histórico."""
        data_adicao = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            self.db_cursor.execute("""
                INSERT INTO historico_estoque (remedio_id, quantidade_adicionada, data_adicao)
                VALUES (?, ?, ?)
            """, (remedio_id, quantidade, data_adicao))
        except sqlite3.Error as e:
            # Não incomoda o usuário, apenas loga o erro
            print(f"Erro ao logar estoque: {e}")
            
    def atualizar_lista_remedios(self):
        """Busca os remédios no DB e atualiza a lista (Treeview)."""
        
        # Limpa a lista antiga
        for item in self.lista_remedios.get_children():
            self.lista_remedios.delete(item)
            
        try:
            self.db_cursor.execute("SELECT id, nome, doses_por_dia, estoque_atual FROM remedios")
            remedios = self.db_cursor.fetchall()
            
            for remedio in remedios:
                remedio_id, nome, doses_dia, estoque = remedio
                
                dias, data_fim = self.calcular_previsao(estoque, doses_dia)
                
                # O 'tags' é um truque para guardar o ID do DB
                # sem precisar mostrá-lo em uma coluna
                self.lista_remedios.insert('', 'end', 
                                           values=(nome, doses_dia, estoque, dias, data_fim),
                                           tags=(remedio_id,))
                
        except sqlite3.Error as e:
            messagebox.showerror("Erro de Banco de Dados", f"Erro ao buscar remédios: {e}")

    def calcular_previsao(self, estoque, doses_dia):
        """Calcula os dias restantes e a data de término."""
        if doses_dia <= 0:
            return "N/A", "N/A"
            
        try:
            dias_restantes = int(estoque / doses_dia)
            data_fim = datetime.now() + timedelta(days=dias_restantes)
            
            return f"{dias_restantes} dias", data_fim.strftime("%d/%m/%Y")
            
        except Exception:
            return "Erro", "Erro"
            
    # --- Lógica de Notificação (COM CORREÇÃO DE THREADING) ---

    def agendar_notificacao_main_thread(self, titulo, mensagem):
        """
        Esta função é chamada pela thread principal (via root.after)
        e é a ÚNICA que pode, com segurança, criar o ToastNotifier.
        
        --- CORREÇÃO DE BUG WNDPROC ---
        Reutiliza o objeto self.toaster pré-inicializado.
        """
        
        # Verifica se o notificador foi initialized com sucesso no __init__
        if not self.toaster:
            print("Notificador não está disponível, exibição pulada.")
            return
            
        try:
            # Reutiliza o objeto 'self.toaster' em vez de criar um novo
            self.toaster.show_toast(
                title=titulo,
                msg=mensagem,
                duration=10, # Duração em segundos
                icon_path=None, # Pode adicionar um ícone .ico aqui
                threaded=True  # <-- ESTA É A CORREÇÃO FINAL (evita bloquear a thread principal)
            )
            print(f"Notificação agendada exibida: {titulo}")
        except Exception as e:
            # Esta exceção pode acontecer se o toast for chamado
            # enquanto outro toast ainda está ativo.
            print(f"Erro ao exibir notificação (self.toaster.show_toast): {e}")


    def _verificar_estoque_notificacao(self):
        """Verifica o estoque e agenda notificações se necessário.
        IMPORTANTE: Esta função roda em uma thread separada e DEVE
        criar sua própria conexão com o DB.
        """
        global NOTIFIER_AVAILABLE # Precisamos ler a variável global
        if not NOTIFIER_AVAILABLE:
            return # Não faz nada se a biblioteca não estiver instalada
            
        # Limite de dias para notificar
        LIMITE_DIAS = 5 
        
        conn_thread = None  # Conexão local da thread
        try:
            # 1. Cria uma conexão com o DB específica para esta thread
            conn_thread = sqlite3.connect(self.db_name)
            # 1b. Habilita chaves estrangeiras na thread
            conn_thread.execute("PRAGMA foreign_keys = ON;")
            cursor_thread = conn_thread.cursor()
            
            # 2. Usa o cursor local da thread
            cursor_thread.execute("SELECT nome, estoque_atual, doses_por_dia FROM remedios")
            remedios = cursor_thread.fetchall()
            
            notificacao_enviada = False

            for nome, estoque, doses_dia in remedios:
                if doses_dia > 0:
                    dias_restantes = int(estoque / doses_dia)
                    
                    if dias_restantes <= LIMITE_DIAS:
                        print(f"Estoque baixo detectado para: {nome}")
                        notificacao_enviada = True
                        
                        titulo = "Alerta de Estoque Baixo!"
                        mensagem = f"O remédio '{nome}' está acabando. Restam apenas {dias_restantes} dias ({estoque} unidades)."
                        
                        # ***** CORREÇÃO IMPORTANTE *****
                        # Não chame o ToastNotifier daqui (thread de fundo).
                        # Peça para a thread principal (UI) fazer isso.
                        self.root.after(0, self.agendar_notificacao_main_thread, titulo, mensagem)
                        
                        # Pausa para não sobrecarregar o Windows com notificações
                        # (6 segundos entre cada notificação)
                        time.sleep(6) 
            
            if notificacao_enviada:
                print("Verificação de notificações concluída.")

        except Exception as e:
            # Não incomoda o usuário com popups, apenas loga no console
            print(f"Erro na thread de notificação: {e}")
            
        finally:
            # 3. Garante que a conexão da thread seja fechada, não importa o que aconteça
            if conn_thread:
                conn_thread.close()

    def _loop_notificacao(self):
        """Loop infinito que roda em segundo plano para verificar o estoque."""
        print("Thread de notificação iniciada.")
        
        # Espera 10 segundos ao iniciar o app pela primeira vez
        time.sleep(10) 
        
        while True:
            print("Executando verificação de estoque em segundo plano...")
            self._verificar_estoque_notificacao()
            
            # Espera 4 horas (4 * 60 * 60 segundos)
            time.sleep(4 * 3600) 
            # Para testar (a cada 30 segundos):
            # time.sleep(30)

    def iniciar_verificador_notificacoes(self):
        """Cria e inicia a thread de notificação."""
        global NOTIFIER_AVAILABLE # Precisamos ler a variável global
        if not NOTIFIER_AVAILABLE:
            print("Notificações desabilitadas (win10toast não encontrada).")
            return
            
        # Cria uma "daemon thread" (ela fecha automaticamente se o programa principal fechar)
        thread = threading.Thread(target=self._loop_notificacao, daemon=True)
        thread.start()

    # Adiciona a necessidade de ler 'global' também em 'testar_notificacao_agora'
    # (Embora já estivesse lá, é bom garantir)
    def testar_notificacao_agora(self):
        """Força uma verificação de estoque e notificação (para teste)."""
        global NOTIFIER_AVAILABLE 
        if not NOTIFIER_AVAILABLE:
            messagebox.showwarning("Biblioteca Ausente", 
                                   "A biblioteca 'win10toast' não está instalada.\nInstale com: pip install win10toast")
            return
        
        messagebox.showinfo("Teste Iniciado", "A verificação de notificação foi iniciada em segundo plano.\n\nSe algum remédio estiver com 5 dias ou menos de estoque, você receberá um aviso em alguns segundos.")
        
        # Inicia a verificação em uma thread separada para não travar a UI
        threading.Thread(target=self._verificar_estoque_notificacao, daemon=True).start()

# --- Ponto de entrada da aplicação ---

if __name__ == "__main__":
    root = tk.Tk()
    
    # --- ADICIONA O ÍCONE ---
    try:
        # Garante que o ícone esteja na mesma pasta que o script
        icon = tk.PhotoImage(file='cardiogram.png')
        root.iconphoto(True, icon)
    except tk.TclError:
        # Caso o arquivo .png não seja encontrado
        print("Arquivo 'cardiogram.png' não encontrado. Usando ícone padrão.")
    except Exception as e:
        # Outros erros (ex: formato não suportado, permissão)
        print(f"Não foi possível carregar o ícone: {e}")
    # --- FIM DA ADIÇÃO DO ÍCONE ---
    
    app = App(root)
    root.mainloop()