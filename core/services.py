from collections import defaultdict
from .models import RegistroProducao
from django.utils import timezone
from django.core.paginator import Paginator


def filtrar_registros(request):
    data_inicio = request.GET.get("data_inicio", "")
    data_fim = request.GET.get("data_fim", "")
    setor_id = request.GET.get("setor", "")
    operador_id = request.GET.get("operador", "")

    filtros = {
        "data_inicio": data_inicio,
        "data_fim": data_fim,
        "setor_id": setor_id,
        "operador_id": operador_id,
    }

    # 1. Checa se o usuário enviou algum filtro preenchido
    tem_filtro_ativo = any([data_inicio, data_fim, setor_id, operador_id])

    # 2. Se nenhum filtro foi selecionado, retorna uma QuerySet vazia sem consultar o banco
    if not tem_filtro_ativo:
        return RegistroProducao.objects.none(), filtros

    # 3. Caso tenha filtros, monta a consulta normalmente
    registros_qs = RegistroProducao.objects.select_related(
        "item_ficha__ficha__operador",
        "item_ficha__ficha__operador__setor",
        "item_ficha__modelo",
    ).order_by("registrado_em")

    if data_inicio:
        registros_qs = registros_qs.filter(
            registrado_em__date__gte=data_inicio
        )
    if data_fim:
        registros_qs = registros_qs.filter(registrado_em__date__lte=data_fim)
    if setor_id:
        registros_qs = registros_qs.filter(
            item_ficha__ficha__operador__setor_id=setor_id
        )
    if operador_id:
        registros_qs = registros_qs.filter(
            item_ficha__ficha__operador_id=operador_id
        )

    return registros_qs, filtros


def processar_relatorio_operadores(registros_qs, page=1, per_page=10):
    """Agrupa os registros paginando os operadores antes do processamento intensivo."""

    # 1. Identifica apenas os IDs dos operadores presentes na QuerySet filtrada
    operador_ids = (
        registros_qs.values_list("item_ficha__ficha__operador__id", flat=True)
        .distinct()
        .order_by("item_ficha__ficha__operador__nome")
    )

    # 2. Pagina os IDs dos Operadores no nível do Banco/Lista leve
    paginator = Paginator(operador_ids, per_page)
    pagina_operadores = paginator.get_page(page)

    # 3. Filtra a QuerySet original APENAS para os operadores da página atual
    registros_pagina = registros_qs.filter(
        item_ficha__ficha__operador__id__in=pagina_operadores.object_list
    )

    # --- DAQUI EM DIANTE O LOOP RODA APENAS PARA OS OPERADORES DA PÁGINA ---
    operadores_map = {}

    for reg in registros_pagina:
        operador = reg.item_ficha.ficha.operador
        op_id = operador.id

        if op_id not in operadores_map:
            operadores_map[op_id] = {
                "operador": {
                    "id": operador.id,
                    "nome": operador.nome,
                    "setor_nome": (
                        operador.setor.nome if operador.setor else "Sem Setor"
                    ),
                },
                "registros": [],
            }

        operadores_map[op_id]["registros"].append(reg)

    relatorio_operadores = []

    for op_id, dados in operadores_map.items():
        registros = dados["registros"]

        modelos_dict = {}
        total_produzido = 0
        total_perda = 0

        horas_dict = defaultdict(
            lambda: {"qtd_apontamentos": 0, "produzido": 0, "perda": 0}
        )

        for reg in registros:
            item_ficha = reg.item_ficha
            modelo_num = (
                item_ficha.modelo.numero
                if item_ficha.modelo
                else "Sem Modelo"
            )
            tamanho = (
                str(item_ficha.numeracao) if item_ficha.numeracao else "Par"
            )

            chave_modelo = (modelo_num, tamanho)
            if chave_modelo not in modelos_dict:
                modelos_dict[chave_modelo] = {
                    "modelo": modelo_num,
                    "numero": tamanho,
                    "produzido": 0,
                }

            modelos_dict[chave_modelo]["produzido"] += reg.quantidade_produzida

            total_produzido += reg.quantidade_produzida
            total_perda += reg.quantidade_perda

            # Ajuste Fuso Horário
            data_local = timezone.localtime(reg.registrado_em)
            hora_str = data_local.strftime("%H:00")

            horas_dict[hora_str]["qtd_apontamentos"] += 1
            horas_dict[hora_str]["produzido"] += reg.quantidade_produzida
            horas_dict[hora_str]["perda"] += reg.quantidade_perda

        resumo_modelos = sorted(
            modelos_dict.values(), key=lambda x: (x["modelo"], x["numero"])
        )

        baixas_por_hora = []
        for hora in sorted(horas_dict.keys()):
            prod = horas_dict[hora]["produzido"]
            perda = horas_dict[hora]["perda"]
            hora_num = int(hora.split(":")[0])

            baixas_por_hora.append(
                {
                    "intervalo_hora": f"{hora_num:02d}:00 - {hora_num:02d}:59",
                    "qtd_apontamentos": horas_dict[hora]["qtd_apontamentos"],
                    "produzido": prod,
                    "perda": perda,
                    "total_hora": prod,
                }
            )

        relatorio_operadores.append(
            {
                "operador": dados["operador"],
                "resumo_modelos": resumo_modelos,
                "total_produzido": total_produzido,
                "total_perda": total_perda,
                "baixas_por_hora": baixas_por_hora,
                "tem_planejamento": False,
            }
        )

    # Retorna os dados processados DA PÁGINA + o objeto paginator para montar o HTML
    return relatorio_operadores, pagina_operadores