# ==================== VIEWS.PY ====================
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, logout, authenticate
from django.contrib import messages
from django.core.paginator import Paginator
from django.utils import timezone
from django.urls import reverse
from django.http import JsonResponse
from django.db import IntegrityError, transaction
from django.db.models import Case, When, Value, IntegerField, Q , Max, F, Count, Sum
from .models import Usuario, Modelo, Peca, Ficha, ItemFicha, RegistroProducao, ItemFichaPeca, Setor, Operador, GradeHorario
from .forms import RegistroUsuarioForm, ModeloForm, PecaForm, FichaForm, ItemFichaForm, RegistroProducaoForm, ItemFichaPecaForm, SetorForm, OperadorForm, GradeHorarioForm, IntervaloHorarioFormSet
from datetime import datetime, timedelta
from django.views.decorators.http import require_POST
from decimal import Decimal
from django.db.models.functions import Length
import os
import json

def login_view(request):
    if request.user.is_authenticated:
        return redirect('inicio')
    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']
        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            return redirect('inicio')
        messages.error(request, 'Nome de usuário ou senha inválidos.')
    return render(request, 'core/login.html')

def logout_view(request):
    logout(request)
    return redirect('login')

def csrf_failure_view(request, reason=""):
    # Adiciona a mensagem que o usuário vai ler ao chegar no login
    messages.warning(request, "Sua sessão expirou por inatividade. Por favor, entre novamente.")
    
    # Redireciona para a página de login
    return redirect('login') # nome da URL de login

def registrar_view(request):
    if request.user.is_authenticated and request.user.tipo != 'admin':
        return redirect('inicio')
        
    if request.method == 'POST':
        form = RegistroUsuarioForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Conta criada com sucesso! Você já pode fazer login.')
            return redirect('inicio')
    else:
        form = RegistroUsuarioForm()
        
    return render(request, 'core/registrar.html', {'form': form})


# ==================== TELAS DE INICIO ====================

@login_required
def inicio(request):
    if request.user.tipo == 'admin':
        return redirect('inicio_administrador')
    # Se não for agente, trata como solicitante
    else: 
        return redirect('inicio_supervisor')

@login_required
def inicio_administrador(request):
    hoje = timezone.localdate()
 
    # Números gerais que viram os cards do topo
    stats = {
        'modelos': Modelo.objects.filter(ativo=True).count(),
        'pecas': Peca.objects.count(),
        'fichas_hoje': Ficha.objects.filter(data_criacao=hoje).count(),
        'usuarios': Usuario.objects.filter(is_active=True).count(),
    }
 
    # As últimas fichas abertas no sistema, com a contagem de modelos
    # que cada uma tem (pra mostrar "3 modelos" sem precisar de outra query por linha)
    fichas_list = (
        Ficha.objects
        .select_related('usuario', 'operador')
        .annotate(
            total_modelos=Count('itens__modelo', distinct=True),
            total_itens=Count('itens', distinct=True),
            total_pecas=Count('itens__pecas_habilitadas', distinct=True)
        )
        .order_by('-criado_em')
    )

    paginator = Paginator(fichas_list, 10)
    page_number = request.GET.get('page')
    fichas_page = paginator.get_page(page_number)
    
    return render(request, 'core/inicio_administrador.html', {
        'stats': stats,
        'fichas_recentes': fichas_page,
    })

    
@login_required
def inicio_supervisor(request):
    fichas_list = (
        Ficha.objects
        .filter(usuario=request.user)
        .prefetch_related('itens__modelo', 'itens__registros', 'itens__pecas_habilitadas') 
        .order_by('-criado_em')
        .annotate(
            total_modelos=Count('itens__modelo', distinct=True),
            total_itens=Count('itens', distinct=True),
            total_pecas=Count('itens__pecas_habilitadas', distinct=True)
        )
    )

    paginator = Paginator(fichas_list, 10)
    page_number = request.GET.get('page')
    fichas_page = paginator.get_page(page_number)

    fichas_resumo = []
    for ficha in fichas_page:
        itens = []
        total_produzido_ficha = 0
        total_planejado_ficha = 0

        for item in ficha.itens.all():
            produzido = item.registros.aggregate(
                total=Sum('quantidade_produzida')
            )['total'] or 0

            total_produzido_ficha += produzido
            if item.quantidade_planejada:
                total_planejado_ficha += item.quantidade_planejada

            itens.append({
                'modelo': item.modelo,
                'produzido': produzido,
                'meta_hora': item.modelo.pares_por_hora,
                'quantidade_planejada': item.quantidade_planejada,
            })

        pct_concluido = None
        if ficha.tipo == 'numerada' and total_planejado_ficha > 0:
            pct_concluido = min(100, round((total_produzido_ficha / total_planejado_ficha) * 100))

        fichas_resumo.append({
            'ficha': ficha,
            'itens': itens,
            'qtd_modelos': ficha.total_modelos, # <--- Vem do annotate!
            'qtd_pecas': ficha.total_pecas,     # <--- Vem do annotate!
            'total_produzido': total_produzido_ficha,
            'total_planejado': total_planejado_ficha,
            'pct_concluido': pct_concluido,
        })

    return render(request, 'core/inicio_supervisor.html', {
        'fichas_resumo': fichas_resumo,
        'fichas_page': fichas_page,
        'total_fichas': len(fichas_resumo),
    })

# =================== SETORES E OPERADORES =====================

@login_required
def listar_setores(request):
    setores_list = Setor.objects.all().order_by('nome')
    form = SetorForm(request.POST or None)

    if request.method == 'POST':
        # Se veio um ID no POST, é uma EDIÇÃO
        setor_id = request.POST.get('setor_id')
        if setor_id:
            setor = get_object_or_404(Setor, pk=setor_id)
            form_edit = SetorForm(request.POST, instance=setor)
            if form_edit.is_valid():
                form_edit.save()
                messages.success(request, f'Setor "{setor.nome}" atualizado com sucesso!')
                return redirect('listar_setores')
        else:
            # Se NÃO veio ID, é um CADASTRO NOVO
            if form.is_valid():
                form.save()
                messages.success(request, 'Setor cadastrado com sucesso!')
                return redirect('listar_setores')

    # paginação, 10 por página
    paginator = Paginator(setores_list, 10)
    page_number = request.GET.get('page')
    setores = paginator.get_page(page_number)

    return render(request, 'core/setores_lista.html', {
        'setores': setores,
        'form': form,
    })


@login_required
def listar_operadores(request):
    setor_id = request.GET.get('setor')
    operadores_list = Operador.objects.select_related('setor').all().order_by('nome')

    # Filtro opcional por setor na tela de listagem
    if setor_id:
        operadores = operadores_list.filter(setor_id=setor_id)

    form = OperadorForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Operador cadastrado com sucesso!')
        return redirect('listar_operadores')

    # paginação, 10 por pagina
    paginator = Paginator(operadores_list,10)
    page_number = request.GET.get('page')
    operadores = paginator.get_page(page_number)

    setores = Setor.objects.all().order_by('nome')

    return render(request, 'core/operadores_lista.html', {
        'operadores': operadores,
        'setores': setores,
        'form': form,
        'setor_selecionado': int(setor_id) if setor_id and setor_id.isdigit() else None,
    })

@login_required
def alterar_status_operador(request, operador_id):
    if not request.user.is_admin:
        messages.error(request, "Ação não permitida.")
        return redirect("listar_operadores")

    operador = get_object_or_404(Operador, pk=operador_id)

    # Regra de Segurança: Verifica se há registros/fichas apontados para este operador
    # Supondo que a relação se chame 'apontamento_set' ou 'ficha_set' (ajuste o nome da relação se necessário)
    tem_apontamentos = (
        hasattr(operador, "apontamento_set") and operador.apontamento_set.exists()
    )

    if tem_apontamentos:
        messages.error(
            request,
            f"O operador '{operador.nome}' não pode ser alterado pois já possui"
            " apontamentos de produção registrados.",
        )
    else:
        operador.ativo = not operador.ativo
        operador.save()
        status_txt = "ativado" if operador.ativo else "desativado"
        messages.success(
            request, f"Operador '{operador.nome}' {status_txt} com sucesso."
        )

    return redirect("listar_operadores")


@login_required
def excluir_operador(request, operador_id):
    if not request.user.is_admin:
        messages.error(request, "Ação não permitida.")
        return redirect("listar_operadores")

    operador = get_object_or_404(Operador, pk=operador_id)

    # Regra de Segurança: Impede exclusão caso haja histórico de produção
    tem_apontamentos = (
        hasattr(operador, "apontamento_set") and operador.apontamento_set.exists()
    )

    if tem_apontamentos:
        messages.error(
            request,
            f"O operador '{operador.nome}' não pode ser excluído pois possui"
            " histórico no sistema.",
        )
    else:
        operador.delete()
        messages.success(
            request, f"Operador '{operador.nome}' excluído com sucesso."
        )

    return redirect("listar_operadores")
# ==================== MODELOS E PEÇAS ====================

@login_required
def cadastro_modelo(request):
    if not request.user.is_admin:
        messages.error(
            request, "Apenas administradores podem gerenciar modelos."
        )
        return redirect("inicio_supervisor")

    if request.method == "POST":
        form = ModeloForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Modelo cadastrado com sucesso.")
            return redirect("cadastro_modelo")
    else:
        form = ModeloForm()

    # Ordena pelo campo 'numero'
    modelos_list = Modelo.objects.annotate(
        total_usos=Count('itemficha'), tamanho_numero=Length('numero')
        ).order_by('tamanho_numero', 'numero')

    # Paginação: exibe 15 modelos por página (ajuste conforme preferir)
    paginator = Paginator(modelos_list, 15)
    page_number = request.GET.get("page")
    modelos = paginator.get_page(page_number)

    return render(
        request,
        "core/cadastro_modelo.html",
        {
            "form": form,
            "modelos": modelos,
        },
    )

@login_required
def alterar_status_modelo(request, modelo_id):
    if not request.user.is_admin:
        messages.error(request, "Ação não permitida.")
        return redirect('cadastro_modelo')

    modelo = get_object_or_404(Modelo, pk=modelo_id)

    # Regra de Segurança: Impede se houver fichas vinculadas
    if modelo.itemficha_set.exists():
        messages.error(request, f"O modelo #{modelo.numero} não pode ser alterado pois já está em uso em fichas de produção.")
    else:
        modelo.ativo = not modelo.ativo
        modelo.save()
        status_txt = "ativado" if modelo.ativo else "desativado"
        messages.success(request, f"Modelo #{modelo.numero} {status_txt} com sucesso.")

    return redirect('cadastro_modelo')


@login_required
def excluir_modelo(request, modelo_id):
    if not request.user.is_admin:
        messages.error(request, "Ação não permitida.")
        return redirect('cadastro_modelo')

    modelo = get_object_or_404(Modelo, pk=modelo_id)

    # Impede a exclusão caso o modelo esteja em algum ItemFicha
    if modelo.itemficha_set.exists():
        messages.error(request, f"O modelo #{modelo.numero} não pode ser excluído pois já está em uso em fichas de produção.")
    else:
        modelo.delete()
        messages.success(request, f"Modelo #{modelo.numero} excluído com sucesso.")

    return redirect('cadastro_modelo')
 
 
@login_required
def cadastro_peca(request):
    if not request.user.is_admin:
        messages.error(request, "Apenas administradores podem gerenciar peças.")
        return redirect('inicio_supervisor')

    if request.method == 'POST':
        form = PecaForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Peça cadastrada com sucesso.")
            return redirect('cadastro_peca')
    else:
        form = PecaForm()

    # Conta em quantos ItemFichaPeca a peça está habilitada (via related_name 'habilitacoes')
    pecas = Peca.objects.select_related('modelo').annotate(
        total_usos=Count('habilitacoes')
    ).order_by('-id')

    # Dicionário com limite de tempo por modelo para o JS
    modelos = Modelo.objects.filter(ativo=True)
    tempos_por_modelo = {m.id: str(m.tempo_fabricacao) for m in modelos}

    return render(request, 'core/cadastro_peca.html', {
        'form': form,
        'pecas': pecas,
        'tempos_por_modelo': tempos_por_modelo,
    })

@login_required
def alterar_status_peca(request, peca_id):
    if not request.user.is_admin:
        messages.error(request, "Ação não permitida.")
        return redirect('cadastro_peca')

    peca = get_object_or_404(Peca, pk=peca_id)

    # Bloqueia se a peça estiver habilitada em algum ItemFichaPeca
    if peca.habilitacoes.exists():
        messages.error(request, f"A peça '{peca.nome}' não pode ter o status alterado pois já está em uso em fichas de produção.")
    else:
        peca.ativo = not peca.ativo
        peca.save()
        status_txt = "ativada" if peca.ativo else "desativada"
        messages.success(request, f"Peça '{peca.nome}' {status_txt} com sucesso.")

    return redirect('cadastro_peca')

@login_required
def excluir_peca(request, peca_id):
    if not request.user.is_admin:
        messages.error(request, "Ação não permitida.")
        return redirect('cadastro_peca')

    peca = get_object_or_404(Peca, pk=peca_id)

    # Bloqueia a exclusão se a peça estiver habilitada em algum ItemFichaPeca
    if peca.habilitacoes.exists():
        messages.error(request, f"A peça '{peca.nome}' não pode ser excluída pois já está em uso em fichas de produção.")
    else:
        peca.delete()
        messages.success(request, f"Peça '{peca.nome}' excluída com sucesso.")

    return redirect('cadastro_peca')



# ==================== FICHAS DE TEMPO DE PRODUÇÃO ====================

def _usuario_pode_ver_ficha(user, ficha):
    """Admin vê tudo. Supervisor só vê as próprias fichas."""
    return user.is_admin or ficha.usuario_id == user.id
 
 
@login_required
def criar_ficha(request):
    if request.method == 'POST':
        # Passa o 'request.user' para o formulário validar e filtrar os operadores
        form = FichaForm(request.POST, user=request.user)
        if form.is_valid():
            ficha = form.save(commit=False)
            ficha.usuario = request.user  # Garante a autoria no supervisor logado
            ficha.save()
            messages.success(request, f"Ficha #{ficha.id} criada. Agora adicione os modelos.")
            return redirect('detalhe_ficha', ficha_id=ficha.id)
    else:
        # Passa o 'request.user' também no GET para carregar o <select> filtrado
        form = FichaForm(user=request.user)

    return render(request, 'core/criar_ficha.html', {'form': form})
 

# os totais e informações de registro dos modelos são feitos na view, mas o resto, das peças, é puxado direto dos propertys no model
@login_required
def detalhe_ficha(request, ficha_id):
    """
    Tela de TRABALHO do supervisor — focado em registro rápido de produção.
    """
    # 1. Incluídos 'grade_horario__intervalos' e 'registros' nos prefetches
    ficha = get_object_or_404(
        Ficha.objects
        .select_related('usuario', 'grade_horario')
        .prefetch_related(
            'grade_horario__intervalos',
            'itens__modelo__pecas',
            'itens__pecas_habilitadas__peca',
            'itens__registros'
        ),
        pk=ficha_id
    )

    if request.user.is_admin:
        return redirect('visualizar_ficha', ficha_id=ficha.id)

    if ficha.usuario_id != request.user.id:
        messages.error(request, "Você só pode abrir fichas que você mesmo criou.")
        return redirect('inicio_supervisor')

    item_form = ItemFichaForm(ficha=ficha)

    # 2. Mapeamento de próximos períodos por item/peça
    proximos_periodos = {}
    for item in ficha.itens.all():
        # Período para o Modelo (item sem peça específica)
        proximo_modelo = item.proximo_periodo()
        if proximo_modelo:
            proximos_periodos[str(item.id)] = {
                'id': proximo_modelo.id,
                'rotulo': str(proximo_modelo) # Ex: "07:00 - 08:00" ou campo de rótulo da grade
            }

        # Período para cada Peça habilitada do item
        for hab in item.pecas_habilitadas.all():
            proximo_peca = hab.proximo_periodo()
            if proximo_peca:
                chave_peca = f"{item.id}_{hab.peca_id}"
                proximos_periodos[chave_peca] = {
                    'id': proximo_peca.id,
                    'rotulo': str(proximo_peca)
                }

    # 3. Define o período inicial do form baseado no primeiro item (se existir)
    primeiro_item = ficha.itens.first()
    periodo_inicial_obj = primeiro_item.proximo_periodo() if primeiro_item else None
    periodo_inicial_id = periodo_inicial_obj.id if periodo_inicial_obj else None

    registro_form = RegistroProducaoForm(
        ficha=ficha, 
        initial={'periodo': periodo_inicial_id} if periodo_inicial_id else None
    )

    if request.method == 'POST':
        acao = request.POST.get('acao')

        if acao == 'adicionar_modelo':
            item_form = ItemFichaForm(request.POST, ficha=ficha)
            if item_form.is_valid():
                try:
                    with transaction.atomic():
                        item_form.save()
                    messages.success(request, "Modelo e numeração adicionados à ficha.")
                    return redirect('detalhe_ficha', ficha_id=ficha.id)
                except IntegrityError:
                    item_form.add_error('numeracao', "Este mesmo modelo com esta numeração já foi adicionado a esta ficha.")

        elif acao == 'adicionar_peca':
            peca_form = ItemFichaPecaForm(request.POST, ficha=ficha)
            if peca_form.is_valid():
                try:
                    with transaction.atomic():
                        peca_form.save()
                    messages.success(request, "Peça habilitada para registro.")
                    return redirect('detalhe_ficha', ficha_id=ficha.id)
                except IntegrityError:
                    messages.error(request, "Essa peça já foi adicionada a este modelo, nesta ficha.")
            else:
                primeiro_erro = next(iter(peca_form.errors.values()))[0] if peca_form.errors else "Dados inválidos."
                messages.error(request, primeiro_erro)

        elif acao == 'registrar_producao':
            registro_form = RegistroProducaoForm(request.POST, ficha=ficha)
            if registro_form.is_valid():
                try:
                    registro_form.save()
                    messages.success(request, "Produção registrada com sucesso.")
                    return redirect('detalhe_ficha', ficha_id=ficha.id)
                except IntegrityError:
                    messages.error(
                        request, 
                        "Já existe um registro de produção para este mesmo período/horário neste item."
                    )
            else:
                primeiro_erro = next(iter(registro_form.errors.values()))[0] if registro_form.errors else "Dados inválidos."
                messages.error(request, primeiro_erro)

    # Dados consolidados dos itens simples
    itens_simples = []
    metas_por_item = {}
    pecas_por_item = {}

    for item in ficha.itens.all():
        pecas_habilitadas = list(item.pecas_habilitadas.all())
        ids_hab = [h.peca_id for h in pecas_habilitadas]

        totais_modelo = item.registros.filter(
            peca__isnull=True
        ).aggregate(
            total_produzido=Sum('quantidade_produzida'),
            total_perda=Sum('quantidade_perda')
        )
        total_produzido_modelo = totais_modelo['total_produzido'] or 0
        total_perda_modelo = totais_modelo['total_perda'] or 0

        itens_simples.append({
            'item': item,
            'modelo': item.modelo,
            'meta_hora': item.modelo.pares_por_hora,
            'pecas_habilitadas': pecas_habilitadas,
            'pecas_disponiveis': item.modelo.pecas.exclude(id__in=ids_hab),
            'total_produzido': total_produzido_modelo,
            'total_perda': total_perda_modelo,
        })

        metas_por_item[item.id] = float(item.modelo.pares_por_hora)
        pecas_por_item[item.id] = [
            {'id': h.peca.id, 'nome': h.peca.nome, 'meta_hora': float(h.peca.pares_por_hora)}
            for h in pecas_habilitadas
        ]

    # Últimos 10 lançamentos de produção
    ultimos_registros = (
        RegistroProducao.objects
        .filter(item_ficha__ficha=ficha)
        .select_related('item_ficha__modelo', 'peca', 'periodo')
        .order_by('-registrado_em')[:10]
    )

    for reg in ultimos_registros:
        num_modelo = f"{reg.item_ficha.modelo.numero} (Nº {reg.item_ficha.numeracao})"
        if reg.peca:
            reg.item_rotulo = f"{num_modelo} — {reg.peca.nome}"
            reg.meta_padrao = reg.peca.pares_por_hora
        else:
            reg.item_rotulo = f"{num_modelo}"
            reg.meta_padrao = reg.item_ficha.modelo.pares_por_hora

        reg.meta_planejada = reg.item_ficha.quantidade_planejada if ficha.tipo == 'numerada' else None
        reg.diferenca = reg.quantidade_produzida - reg.meta_padrao
        reg.na_meta = reg.quantidade_produzida >= reg.meta_padrao

    tempos_por_modelo = {m.id: float(m.tempo_fabricacao) for m in Modelo.objects.filter(ativo=True)}

    return render(request, 'core/detalhe_ficha.html', {
        'ficha': ficha,
        'itens_simples': itens_simples,
        'ultimos_registros': ultimos_registros,
        'item_form': item_form,
        'registro_form': registro_form,
        'tempos_por_modelo': tempos_por_modelo,
        'metas_por_item': metas_por_item,
        'pecas_por_item': pecas_por_item,
        'proximos_periodos_json': json.dumps(proximos_periodos), # 4. Serializado para uso no JS
    })


@login_required
def visualizar_ficha(request, ficha_id):
    ficha = get_object_or_404(
        Ficha.objects
        .select_related('usuario', 'operador')
        .prefetch_related(
            'itens__modelo',
            'itens__registros__periodo',
            'itens__pecas_habilitadas__peca'
        ),
        pk=ficha_id
    )

    if not request.user.is_admin:
        messages.error(request, "Essa tela é só de visualização, disponível para administradores.")
        return redirect('inicio_supervisor')

    eh_numerada = ficha.tipo == 'numerada'
    itens_resumo = []

    for item in ficha.itens.all():
        # --- CÁLCULO DO MODELO (REGISTROS SEM PEÇA) ---
        registros_modelo = [r for r in item.registros.all() if r.peca_id is None]
        produzido = sum(r.quantidade_produzida for r in registros_modelo)
        perda_modelo = sum(r.quantidade_perda for r in registros_modelo)

        horas_modelo = len(registros_modelo)
        meta_hora_modelo = item.modelo.pares_por_hora
        meta_esperada_modelo = horas_modelo * meta_hora_modelo
        na_meta_total_modelo = (produzido >= meta_esperada_modelo) if horas_modelo > 0 else None

        horas_modelo_ok = sum(1 for r in registros_modelo if r.dentro_da_meta)
        percentual_modelo = round(horas_modelo_ok / horas_modelo * 100) if horas_modelo else None

        # Ficha Numerada (Modelo)
        qtd_planejada = item.quantidade_planejada if eh_numerada else None
        qtd_restante = item.qtd_restante(produzido) if eh_numerada else None
        percentual_concluido = item.percentual_concluido(produzido) if eh_numerada else None
        tempo_restante_min = item.tempo_restante_minutos(produzido) if eh_numerada else None
        tempo_restante_formatado = item.tempo_restante_formatado(produzido) if eh_numerada else None

        percentuais_card = [percentual_modelo] if percentual_modelo is not None else []

        # --- CÁLCULO DAS PEÇAS ---
        pecas_resumo = []
        for habilitacao in item.pecas_habilitadas.all():
            registros_peca = [r for r in item.registros.all() if r.peca_id == habilitacao.peca_id]
            produzido_peca = sum(r.quantidade_produzida for r in registros_peca)
            perda_peca = sum(r.quantidade_perda for r in registros_peca)

            horas_peca = len(registros_peca)
            meta_hora_peca = habilitacao.peca.pares_por_hora
            meta_esperada_peca = horas_peca * meta_hora_peca
            na_meta_total_peca = (produzido_peca >= meta_esperada_peca) if horas_peca > 0 else None

            horas_peca_ok = sum(1 for r in registros_peca if r.dentro_da_meta)
            percentual_peca = round(horas_peca_ok / horas_peca * 100) if horas_peca else None

            if percentual_peca is not None:
                percentuais_card.append(percentual_peca)

            qtd_planejada_peca = habilitacao.quantidade_planejada if eh_numerada else None
            qtd_restante_peca = habilitacao.qtd_restante(produzido_peca) if eh_numerada else None
            percentual_concluido_peca = habilitacao.percentual_concluido(produzido_peca) if eh_numerada else None
            tempo_restante_min_peca = habilitacao.tempo_restante_minutos(produzido_peca) if eh_numerada else None
            tempo_restante_formatado_peca = habilitacao.tempo_restante_formatado(produzido_peca) if eh_numerada else None

            pecas_resumo.append({
                'peca': habilitacao.peca,
                'produzido': produzido_peca,
                'perda': perda_peca,
                'meta_hora': meta_hora_peca,
                'horas': horas_peca,
                'meta_esperada': meta_esperada_peca,
                'na_meta_total': na_meta_total_peca,
                'percentual': percentual_peca,
                'na_meta': percentual_peca is not None and percentual_peca >= 50,

                # Dados de Ficha Numerada da Peça
                'qtd_planejada': qtd_planejada_peca,
                'qtd_restante': qtd_restante_peca,
                'percentual_concluido': percentual_concluido_peca,
                'tempo_restante_min': tempo_restante_min_peca,
                'tempo_restante_formatado': tempo_restante_formatado_peca,
                'concluido': (qtd_restante_peca == 0) if eh_numerada else False,
            })

        # Status Geral do Card
        if percentuais_card:
            media_geral = sum(percentuais_card) / len(percentuais_card)
            status_card = 'ok' if media_geral >= 50 else 'alerta'
        else:
            status_card = 'sem_dados'

        itens_resumo.append({
            'item': item,
            'modelo': item.modelo,
            'produzido': produzido,
            'perda': perda_modelo,
            'meta_hora': meta_hora_modelo,
            'horas': horas_modelo,
            'meta_esperada': meta_esperada_modelo,
            'na_meta_total': na_meta_total_modelo,

            # Ficha Numerada (Modelo)
            'qtd_planejada': qtd_planejada,
            'qtd_restante': qtd_restante,
            'percentual_concluido': percentual_concluido,
            'tempo_restante_min': tempo_restante_min,
            'tempo_restante_formatado': tempo_restante_formatado,
            'concluido': (qtd_restante == 0) if eh_numerada else False,

            'tempo_estimado_total': item.tempo_estimado_total,
            'percentual_modelo': percentual_modelo,
            'pecas_resumo': pecas_resumo,
            'status_card': status_card,
        })

    # Registros para a tabela inferior do histórico
    registros = (
        RegistroProducao.objects
        .filter(item_ficha__ficha=ficha)
        .select_related('item_ficha__modelo', 'peca', 'periodo')
        .order_by('periodo__ordem', 'peca__nome')
    )

    return render(request, 'core/visualizar_ficha.html', {
        'ficha': ficha,
        'itens_resumo': itens_resumo,
        'registros': registros,
    })


@login_required
def historico_fichas(request):
    # 1. Captura os parâmetros de filtro passados via URL/GET
    setor_id = request.GET.get('setor')
    supervisor_id = request.GET.get('supervisor')
    operador_id = request.GET.get('operador')

    # 2. Prepara a consulta base
    fichas_list = (
        Ficha.objects
        .select_related('usuario', 'operador')
        .annotate(
            total_modelos=Count('itens__modelo', distinct=True),
            total_itens=Count('itens', distinct=True),
            total_pecas=Count('itens__pecas_habilitadas', distinct=True)
        )
    )

    # 3. Aplica os filtros dinamicamente se foram informados na requisição
    
    # Filtro de Setor (relacionado através do operador ou dos itens da ficha)
    if setor_id:
        # Exemplo: filtrando pelo setor do operador vinculado à ficha
        fichas_list = fichas_list.filter(operador__setor_id=setor_id)

    # Filtro de Supervisor (usuário que criou a ficha)
    if supervisor_id:
        fichas_list = fichas_list.filter(usuario_id=supervisor_id)

    # Filtro de Operador
    if operador_id:
        fichas_list = fichas_list.filter(operador_id=operador_id)

    # 4. Ordenação após aplicar os filtros
    fichas_list = fichas_list.order_by('-criado_em')

    # 5. Paginação
    paginator = Paginator(fichas_list, 10)
    page_number = request.GET.get('page')
    fichas_page = paginator.get_page(page_number)

    # 6. Consultas para preencher os <select> do formulário de filtro
    supervisores = Usuario.objects.filter(tipo=Usuario.Tipo.SUPERVISOR)
    operadores = Operador.objects.all().order_by('nome')
    setores = Setor.objects.all().order_by('nome')

    return render(request, 'core/historico_fichas.html', {
        'fichas': fichas_page,
        'supervisores': supervisores,
        'operadores': operadores,
        'setores': setores,
        # Devolve os valores selecionados para manter o estado dos selects no frontend
        'setor_selecionado': setor_id,
        'supervisor_selecionado': supervisor_id,
        'operador_selecionado': operador_id,
    })

def historico_ficha_usuario(request, usuario_id):
    usuario = get_object_or_404(Usuario, pk=usuario_id)

    # 1. Filtros recebidos por GET
    operador_id = request.GET.get('operador', '')
    data_filtro = request.GET.get('data', '')
    tipo_filtro = request.GET.get('tipo', '')

    # 2. Queryset de Fichas do Supervisor
    fichas_list = (
        Ficha.objects
        .filter(usuario=usuario)
        .select_related('operador', 'operador__setor')
        .annotate(
            total_modelos=Count('itens__modelo', distinct=True),
            total_itens=Count('itens', distinct=True),
            total_pecas=Count('itens__pecas_habilitadas', distinct=True)
        )
    )

    # 3. Filtros dinâmicos
    if operador_id:
        fichas_list = fichas_list.filter(
            operador_id=operador_id,
            operador__setor_id=usuario.setor_id
        )

    if data_filtro:
        fichas_list = fichas_list.filter(criado_em__date=data_filtro)

    if tipo_filtro:
        fichas_list = fichas_list.filter(tipo=tipo_filtro)

    fichas_list = fichas_list.order_by('-criado_em')

    # 4. Todos os operadores ativos do setor do supervisor, para preencher o select de filtro
    operadores = Operador.objects.filter(ativo=True).select_related('setor')
    if usuario.setor_id:
        operadores = operadores.filter(setor_id=usuario.setor_id)
    else:
        # Caso o usuário não tenha setor atribuído, retorna uma lista vazia
        operadores = operadores.none()

    # 5. Paginação
    paginator = Paginator(fichas_list, 10)
    page_number = request.GET.get('page')
    fichas_page = paginator.get_page(page_number)

    return render(request, 'core/historico_ficha_usuario.html', {
        'usuario': usuario,
        'fichas': fichas_page,
        'operadores': operadores,
        'operador_id': operador_id,
        'data_filtro': data_filtro,
        'tipo_filtro': tipo_filtro,
    })

# ==================== HORÁRIOS ====================
def grade_horario_list(request):
    grades = GradeHorario.objects.prefetch_related('intervalos').all()
    # Aponta para o template que MOSTRA a lista e os horários
    return render(request, 'core/grade_horario_lista.html', {'grades': grades})

def grade_horario_create(request):
    if request.method == 'POST':
        form = GradeHorarioForm(request.POST)
        formset = IntervaloHorarioFormSet(request.POST)
        if form.is_valid() and formset.is_valid():
            grade = form.save()
            formset.instance = grade
            formset.save()
            messages.success(request, 'Grade criada com sucesso!')
            return redirect('grade_horario_list')
    else:
        form = GradeHorarioForm()
        formset = IntervaloHorarioFormSet()

    return render(request, 'core/cadastro_grades.html', {
        'form': form,
        'formset': formset,
        'titulo': 'Criar Grade de Horário'
    })

def grade_horario_update(request, pk):
    grade = get_object_or_404(GradeHorario, pk=pk)
    if request.method == 'POST':
        form = GradeHorarioForm(request.POST, instance=grade)
        formset = IntervaloHorarioFormSet(request.POST, instance=grade)
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            messages.success(request, 'Grade atualizada com sucesso!')
            return redirect('grade_horario_list')
    else:
        form = GradeHorarioForm(instance=grade)
        formset = IntervaloHorarioFormSet(instance=grade)

    return render(request, 'core/cadastro_grades.html', {
        'form': form,
        'formset': formset,
        'titulo': 'Editar Grade de Horário'
    })

def grade_horario_delete(request, pk):
    grade = get_object_or_404(GradeHorario, pk=pk)

    if request.method == 'POST':
        # Verifica se existe alguma ficha associada a esta grade
        if grade.fichas.exists():
            messages.warning(
                request,
                'Não é possível excluir esta grade pois existem fichas de produção vinculadas a ela.',
            )
        else:
            grade.delete()
            messages.success(request, 'Grade excluída com sucesso!')

    return redirect('grade_horario_list')