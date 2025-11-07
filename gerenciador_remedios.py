import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import sqlite3
import os
import sys  # Importado para ler argumentos de linha de comando
from datetime import datetime, timedelta
import threading
import time

# Tenta importar a biblioteca de notificação
try:
    from win10toast import ToastNotifier
    NOTIFIER_AVAILABLE = True
except ImportError:
    print("Biblioteca 'win10toast' não encontrada.")
    print("Para receber notificações no Windows, instale com: pip install win10toast")
    NOTIFIER_AVAILABLE = False

class GerenciadorRemediosApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Gerenciador de Remédios")
        self.root.geometry("900x600")

        self.db_conn = None
        self.db_cursor = None
        self.db_name = "remedios.db"

        self._init_db()
        self._create_widgets()
        self.atualizar_lista_remedios()

        # Inicia o verificador de notificações em uma thread separada
        self.iniciar_verificador_notificacoes()

        # Se o script for iniciado com o argumento --minimized, ele começa iconificado
        if "--minimized" in sys.argv:
            self.root.iconify()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _init_db(self):
        """Inicializa a conexão com o banco de dados SQLite e cria as tabelas se não existirem."""
        try:
            self.db_conn = sqlite3.connect(self.db_name)
            self.db_cursor = self.db_conn.cursor()

            # Tabela principal de remédios
            self.db_cursor.execute("""
            CREATE TABLE IF NOT EXISTS remedios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                doses_por_dia INTEGER NOT NULL,
                estoque_atual INTEGER NOT NULL,
                UNIQUE(nome)
            )
            """)

            # Tabela de histórico de adição de estoque
            self.db_cursor.execute("""
            CREATE TABLE IF NOT EXISTS historico_estoque (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                remedio_id INTEGER NOT NULL,
                quantidade_adicionada INTEGER NOT NULL,
                data_adicao TEXT NOT NULL,
                FOREIGN KEY (remedio_id) REFERENCES remedios(id) ON DELETE CASCADE
            )
            """)
            self.db_conn.commit()
            print(f"Banco de dados '{self.db_name}' conectado com sucesso.")

        except sqlite3.Error as e:
            messagebox.showerror("Erro de Banco de Dados", f"Erro ao conectar ao SQLite: {e}")
            self.root.quit()

    def _create_widgets(self):
        """Cria os componentes da interface gráfica."""
        
        # --- Frame de Cadastro ---
        frame_cadastro = ttk.LabelFrame(self.root, text="Cadastrar Novo Remédio", padding=15)
        frame_cadastro.pack(fill="x", padx=10, pady=10)

        ttk.Label(frame_cadastro, text="Nome:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.entry_nome = ttk.Entry(frame_cadastro, width=40)
        self.entry_nome.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

        ttk.Label(frame_cadastro, text="Doses por dia:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.entry_doses = ttk.Entry(frame_cadastro, width=10)
        self.entry_doses.grid(row=1, column=1, padx=5, pady=5, sticky="w")

        ttk.Label(frame_cadastro, text="Estoque Inicial:").grid(row=2, column=0, padx=5, pady=5, sticky="w")
        self.entry_estoque_inicial = ttk.Entry(frame_cadastro, width=10)
        self.entry_estoque_inicial.grid(row=2, column=1, padx=5, pady=5, sticky="w")
        
        frame_cadastro.columnconfigure(1, weight=1) # Faz a coluna 1 (dos entries) expandir

        btn_cadastrar = ttk.Button(frame_cadastro, text="Cadastrar Remédio", command=self.cadastrar_remedio)
        btn_cadastrar.grid(row=0, column=2, rowspan=3, padx=20, pady=5, ipady=10, sticky="ns")

        # --- Frame da Lista de Remédios ---
        frame_lista = ttk.LabelFrame(self.root, text="Meus Remédios", padding=15)
        frame_lista.pack(fill="both", expand=True, padx=10, pady=10)

        # Definindo as colunas da Treeview
        colunas = ("id", "nome", "estoque", "doses_dia", "dias_restantes", "data_fim")
        self.tree_remedios = ttk.Treeview(frame_lista, columns=colunas, show="headings")

        self.tree_remedios.heading("id", text="ID")
        self.tree_remedios.heading("nome", text="Nome")
        self.tree_remedios.heading("estoque", text="Estoque Atual")
        self.tree_remedios.heading("doses_dia", text="Doses/Dia")
        self.tree_remedios.heading("dias_restantes", text="Dias Restantes")
        self.tree_remedios.heading("data_fim", text="Data Prev. Fim")

        # Definindo a largura das colunas
        self.tree_remedios.column("id", width=40, minwidth=30, anchor="center")
        self.tree_remedios.column("nome", width=250, minwidth=150)
        self.tree_remedios.column("estoque", width=100, minwidth=80, anchor="center")
        self.tree_remedios.column("doses_dia", width=80, minwidth=70, anchor="center")
        self.tree_remedios.column("dias_restantes", width=100, minwidth=90, anchor="center")
        self.tree_remedios.column("data_fim", width=120, minwidth=100, anchor="center")
        
        # Scrollbar
        scrollbar = ttk.Scrollbar(frame_lista, orient="vertical", command=self.tree_remedios.yview)
        self.tree_remedios.configure(yscroll=scrollbar.set)
        
        scrollbar.pack(side="right", fill="y")
        self.tree_remedios.pack(fill="both", expand=True)
        
        # --- Frame de Ações ---
        frame_acoes = ttk.Frame(self.root, padding=10)
        frame_acoes.pack(fill="x")
        
        btn_adicionar_estoque = ttk.Button(frame_acoes, text="Adicionar Estoque", command=self.adicionar_estoque_popup)
        btn_adicionar_estoque.pack(side="left", padx=10)
        
        btn_modificar_estoque = ttk.Button(frame_acoes, text="Modificar Estoque", command=self.modificar_estoque_popup)
        btn_modificar_estoque.pack(side="left", padx=5)
        
        btn_excluir = ttk.Button(frame_acoes, text="Excluir Remédio", command=self.excluir_remedio)
        btn_excluir.pack(side="right", padx=10)
        
        btn_atualizar_lista = ttk.Button(frame_acoes, text="Atualizar Lista", command=self.atualizar_lista_remedios)
        btn_atualizar_lista.pack(side="left", padx=10)

    def calcular_previsao(self, estoque, doses_dia):
        """Calcula os dias restantes e a data de término do estoque."""
        if doses_dia <= 0:
            return "N/A", "N/A"
        try:
            dias_restantes = int(estoque / doses_dia)
            data_fim = datetime.now() + timedelta(days=dias_restantes)
            return dias_restantes, data_fim.strftime("%d/%m/%Y")
        except:
            return "Erro", "Erro"

    def atualizar_lista_remedios(self):
        """Busca os remédios no DB e atualiza a Treeview."""
        # Limpa a lista atual
        for item in self.tree_remedios.get_children():
            self.tree_remedios.delete(item)
        
        # Busca novos dados
        try:
            self.db_cursor.execute("SELECT id, nome, estoque_atual, doses_por_dia FROM remedios")
            remedios = self.db_cursor.fetchall()
            
            for remedio in remedios:
                id_remedio, nome, estoque, doses_dia = remedio
                dias_rest, data_fim = self.calcular_previsao(estoque, doses_dia)
                
                # Insere na Treeview
                self.tree_remedios.insert("", "end", values=(id_remedio, nome, estoque, doses_dia, dias_rest, data_fim))

        except sqlite3.Error as e:
            messagebox.showerror("Erro de Banco de Dados", f"Erro ao buscar remédios: {e}")

    def cadastrar_remedio(self):
        """Coleta dados dos campos de entrada e insere no banco de dados."""
        nome = self.entry_nome.get().strip()
        doses_str = self.entry_doses.get().strip()
        estoque_str = self.entry_estoque_inicial.get().strip()

        # Validação
        if not nome or not doses_str or not estoque_str:
            messagebox.showwarning("Campos Vazios", "Por favor, preencha todos os campos.")
            return
        
        try:
            doses = int(doses_str)
            estoque = int(estoque_str)
            if doses <= 0 or estoque < 0:
                raise ValueError("Valores devem ser positivos.")
        except ValueError:
            messagebox.showwarning("Valor Inválido", "Doses por dia e estoque devem ser números inteiros positivos.")
            return

        # Inserção no DB
        try:
            # Insere na tabela principal
            self.db_cursor.execute("INSERT INTO remedios (nome, doses_por_dia, estoque_atual) VALUES (?, ?, ?)",
                                   (nome, doses, estoque))
            remedio_id = self.db_cursor.lastrowid # Pega o ID do remédio recém-criado
            
            # Insere o registro inicial no histórico
            data_hoje = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.db_cursor.execute("INSERT INTO historico_estoque (remedio_id, quantidade_adicionada, data_adicao) VALUES (?, ?, ?)",
                                   (remedio_id, estoque, data_hoje))
            
            self.db_conn.commit()
            
            messagebox.showinfo("Sucesso", f"Remédio '{nome}' cadastrado com sucesso!")
            
            # Limpa os campos
            self.entry_nome.delete(0, "end")
            self.entry_doses.delete(0, "end")
            self.entry_estoque_inicial.delete(0, "end")
            
            # Atualiza a lista
            self.atualizar_lista_remedios()

        except sqlite3.IntegrityError: # Erro de NOME ÚNICO
            messagebox.showerror("Erro", f"O remédio '{nome}' já está cadastrado.")
        except sqlite3.Error as e:
            messagebox.showerror("Erro de Banco de Dados", f"Erro ao cadastrar: {e}")

    def excluir_remedio(self):
        """Exclui o remédio selecionado na lista."""
        selecionado = self.tree_remedios.focus() # Pega o item focado (selecionado)
        if not selecionado:
            messagebox.showwarning("Nenhum Remédio Selecionado", "Por favor, selecione um remédio na lista para excluir.")
            return

        # Pega os valores do item selecionado
        valores = self.tree_remedios.item(selecionado, "values")
        id_remedio = valores[0]
        nome_remedio = valores[1]
        
        if messagebox.askyesno("Confirmar Exclusão", f"Tem certeza que deseja excluir o remédio '{nome_remedio}'?\n\nIsso também excluirá todo o histórico de estoque associado."):
            try:
                # O ON DELETE CASCADE no DB cuidará de excluir o histórico
                self.db_cursor.execute("DELETE FROM remedios WHERE id = ?", (id_remedio,))
                self.db_conn.commit()
                
                messagebox.showinfo("Excluído", f"Remédio '{nome_remedio}' excluído com sucesso.")
                self.atualizar_lista_remedios() # Atualiza a lista
                
            except sqlite3.Error as e:
                messagebox.showerror("Erro de Banco de Dados", f"Erro ao excluir: {e}")

    def adicionar_estoque_popup(self):
        """Abre um popup para adicionar mais estoque ao item selecionado."""
        selecionado = self.tree_remedios.focus()
        if not selecionado:
            messagebox.showwarning("Nenhum Remédio Selecionado", "Por favor, selecione um remédio na lista para adicionar estoque.")
            return
            
        valores = self.tree_remedios.item(selecionado, "values")
        id_remedio = valores[0]
        nome_remedio = valores[1]
        estoque_atual = int(valores[2])
        
        # Pede ao usuário a quantidade a adicionar
        quantidade_str = simpledialog.askstring("Adicionar Estoque", 
                                                f"Remédio: {nome_remedio}\nEstoque Atual: {estoque_atual}\n\nQuanto deseja adicionar?",
                                                parent=self.root)
        
        if quantidade_str:
            try:
                quantidade_adicionada = int(quantidade_str)
                if quantidade_adicionada <= 0:
                    raise ValueError("Quantidade deve ser positiva.")
                    
                # Calcula o novo estoque
                novo_estoque = estoque_atual + quantidade_adicionada
                
                # Atualiza o DB
                self.db_cursor.execute("UPDATE remedios SET estoque_atual = ? WHERE id = ?", (novo_estoque, id_remedio))
                
                # Adiciona ao histórico
                data_hoje = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.db_cursor.execute("INSERT INTO historico_estoque (remedio_id, quantidade_adicionada, data_adicao) VALUES (?, ?, ?)",
                                       (id_remedio, quantidade_adicionada, data_hoje))
                
                self.db_conn.commit()
                
                messagebox.showinfo("Sucesso", f"{quantidade_adicionada} unidades adicionadas ao estoque de '{nome_remedio}'.")
                self.atualizar_lista_remedios() # Atualiza a lista

            except ValueError:
                messagebox.showerror("Valor Inválido", "A quantidade deve ser um número inteiro positivo.")
            except sqlite3.Error as e:
                messagebox.showerror("Erro de Banco de Dados", f"Erro ao adicionar estoque: {e}")

    def modificar_estoque_popup(self):
        """Abre um popup para MODIFICAR o estoque do item selecionado."""
        selecionado = self.tree_remedios.focus()
        if not selecionado:
            messagebox.showwarning("Nenhum Remédio Selecionado", "Por favor, selecione um remédio na lista para modificar o estoque.")
            return
            
        valores = self.tree_remedios.item(selecionado, "values")
        id_remedio = valores[0]
        nome_remedio = valores[1]
        estoque_atual = int(valores[2])
        
        # Pede ao usuário o novo valor do estoque
        novo_estoque_str = simpledialog.askstring("Modificar Estoque", 
                                                f"Remédio: {nome_remedio}\nEstoque Atual: {estoque_atual}\n\nQual o NOVO valor do estoque?",
                                                parent=self.root)
        
        if novo_estoque_str:
            try:
                novo_estoque = int(novo_estoque_str)
                if novo_estoque < 0:
                    raise ValueError("Estoque não pode ser negativo.")
                    
                # Atualiza o DB
                self.db_cursor.execute("UPDATE remedios SET estoque_atual = ? WHERE id = ?", (novo_estoque, id_remedio))
                self.db_conn.commit()
                
                # NOTA: Não adicionamos isso ao histórico de "adições",
                # pois é uma correção manual.
                
                messagebox.showinfo("Sucesso", f"Estoque de '{nome_remedio}' modificado para {novo_estoque}.")
                self.atualizar_lista_remedios() # Atualiza a lista

            except ValueError:
                messagebox.showerror("Valor Inválido", "O estoque deve ser um número inteiro não-negativo.")
            except sqlite3.Error as e:
                messagebox.showerror("Erro de Banco de Dados", f"Erro ao modificar estoque: {e}")

    # --- Lógica de Notificação ---

    def _verificar_estoque_notificacao(self):
        """Verifica o estoque e envia notificações se necessário."""
        if not NOTIFIER_AVAILABLE:
            return # Não faz nada se a biblioteca não estiver instalada
            
        # Limite de dias para notificar
        LIMITE_DIAS = 5 
        
        try:
            self.db_cursor.execute("SELECT nome, estoque_atual, doses_por_dia FROM remedios")
            remedios = self.db_cursor.fetchall()
            
            toaster = ToastNotifier()
            notificacao_enviada = False

            for nome, estoque, doses_dia in remedios:
                if doses_dia > 0:
                    dias_restantes, _ = self.calcular_previsao(estoque, doses_dia)
                    
                    if dias_restantes != "N/A" and int(dias_restantes) <= LIMITE_DIAS:
                        print(f"Enviando notificação para {nome}...")
                        titulo = "Alerta de Estoque Baixo!"
                        mensagem = f"O remédio '{nome}' está acabando!\nEstoque para apenas {dias_restantes} dia(s)."
                        
                        # A função show_toast precisa ser chamada na thread principal
                        # Mas para apps simples, podemos tentar chamar daqui.
                        # Para maior robustez, usaríamos um queue.
                        toaster.show_toast(titulo, mensagem, duration=10, threaded=True)
                        notificacao_enviada = True
                        
                        # Pausa para não sobrecarregar o Windows com notificações
                        time.sleep(6) 
            
            if notificacao_enviada:
                print("Verificação de notificações concluída.")

        except Exception as e:
            # Não incomoda o usuário com popups, apenas loga no console
            print(f"Erro na thread de notificação: {e}")

    def _loop_notificacao(self):
        """Loop que roda em segundo plano verificando o estoque."""
        # Espera 10 segundos na primeira vez para o app carregar
        time.sleep(10)
        
        while True:
            print("Executando verificação de estoque em segundo plano...")
            self._verificar_estoque_notificacao()
            
            # Espera 4 horas (4 * 60 * 60 segundos)
            time.sleep(4 * 3600) 

    def iniciar_verificador_notificacoes(self):
        """Inicia a thread de verificação."""
        notification_thread = threading.Thread(target=self._loop_notificacao, daemon=True)
        notification_thread.start()

    def _on_close(self):
        """Chamado ao fechar a janela."""
        if messagebox.askokcancel("Sair", "Deseja realmente sair?"):
            if self.db_conn:
                self.db_conn.close()
            self.root.destroy()


# --- Bloco de Execução Principal ---
if __name__ == "__main__":
    root = tk.Tk()
    app = GerenciadorRemediosApp(root)
    root.mainloop()