from collections import defaultdict
from .models import RegistroProducao
from django.utils import timezone
from django.core.paginator import Paginator


def filtrar_registros(request):
    data = request.GET.get("data", "")
    setor_id = request.GET.get("setor", "")
    operador_id = request.GET.get("operador", "")

    filtros = {
        "data": data,
        "setor_id": setor_id,
        "operador_id": operador_id,
    }

    # Checa se o usuário enviou algum filtro preenchido
    tem_filtro_ativo = any([data, setor_id, operador_id])

    # Se nenhum filtro foi selecionado, retorna QuerySet vazia
    if not tem_filtro_ativo:
        return RegistroProducao.objects.none(), filtros

    registros_qs = RegistroProducao.objects.select_related(
        "item_ficha__ficha__operador",
        "item_ficha__ficha__operador__setor",
        "item_ficha__modelo",
    ).order_by("registrado_em")

    if data:
        registros_qs = registros_qs.filter(
            registrado_em__date=data
        )
    if setor_id:
        registros_qs = registros_qs.filter(
            item_ficha__ficha__operador__setor_id=setor_id
        )
    if operador_id:
        registros_qs = registros_qs.filter(
            item_ficha__ficha__operador_id=operador_id
        )

    return registros_qs, filtros


def _obter_prod_h_base(reg):
    """Retorna a capacidade de produção por hora (pares_por_hora)

    do Modelo ou da Peça vinculada ao registro.
    """
    peca_obj = reg.peca
    if peca_obj is not None:
        return float(peca_obj.pares_por_hora) if peca_obj else 0.0

    item_ficha = reg.item_ficha
    if item_ficha and item_ficha.modelo:
        return float(item_ficha.modelo.pares_por_hora)

    return 0.0


def _agrupar_registros_por_operador(registros_pagina):
    """Agrupa os registros de produção pelo ID do operador."""
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

    return operadores_map


def _processar_dados_operador(registros):
    """Calcula os totais, resumos de modelos e baixas por hora de um operador."""
    modelos_dict = {}
    itens_ficha_processados = set()

    horas_dict = defaultdict(
        lambda: {
            "qtd_apontamentos": 0,
            "produzido_modelo": 0,
            "produzido_peca": 0,
            "perda": 0,
            "modelos_lancados": defaultdict(
                lambda: {
                    "produzido": 0,
                    "planejado": 0,
                    "perda": 0,
                    "e_peca": False,
                    "nome_peca": "",
                    "modelo_num": "",
                    "tamanho": "",
                    "pares_por_hora": 0.0,
                }
            ),
        }
    )

    totais_operador = {
        "modelo_produzido": 0,
        "modelo_planejado": 0,
        "peca_produzida": 0,
        "peca_planejada": 0,
        "perda": 0,
    }

    for reg in registros:
        item_ficha = reg.item_ficha

        modelo_num = (
            item_ficha.modelo.numero if item_ficha.modelo else "Sem Modelo"
        )
        peca_obj = reg.peca
        e_peca = peca_obj is not None
        peca_nome = peca_obj.nome if e_peca else "Modelo Completo"
        tamanho = (
            str(item_ficha.numeracao) if item_ficha.numeracao else "Par"
        )

        prod_h_base = _obter_prod_h_base(reg)
        descricao_item = (
            f"Mod {modelo_num} - {peca_nome}"
            if e_peca
            else f"Mod {modelo_num} (Completo)"
        )
        qtd_plan_reg = reg.qtd_planejada or 0
        chave_modelo = (modelo_num, peca_nome if e_peca else "", tamanho)

        # --- Consolidação por Modelo ---
        if chave_modelo not in modelos_dict:
            modelos_dict[chave_modelo] = {
                "modelo": modelo_num,
                "peca": peca_nome if e_peca else None,
                "e_peca": e_peca,
                "descricao": descricao_item,
                "numero": tamanho,
                "produzido": 0,
                "planejado": 0,
            }

        modelos_dict[chave_modelo]["produzido"] += reg.quantidade_produzida
        totais_operador["perda"] += reg.quantidade_perda

        if e_peca:
            totais_operador["peca_produzida"] += reg.quantidade_produzida
        else:
            totais_operador["modelo_produzido"] += reg.quantidade_produzida

        id_unico_planejado = f"{item_ficha.id}_{reg.peca_id if e_peca else 'mod'}"

        if id_unico_planejado not in itens_ficha_processados:
            itens_ficha_processados.add(id_unico_planejado)
            modelos_dict[chave_modelo]["planejado"] += qtd_plan_reg

            if e_peca:
                totais_operador["peca_planejada"] += qtd_plan_reg
            else:
                totais_operador["modelo_planejado"] += qtd_plan_reg

        # --- Consolidação por Horário ---
        data_local = timezone.localtime(reg.registrado_em)
        hora_str = data_local.strftime("%H:%M")

        horas_dict[hora_str]["qtd_apontamentos"] += 1
        horas_dict[hora_str]["perda"] += reg.quantidade_perda

        if e_peca:
            horas_dict[hora_str]["produzido_peca"] += reg.quantidade_produzida
        else:
            horas_dict[hora_str]["produzido_modelo"] += (
                reg.quantidade_produzida
            )

        chave_item_hora = f"{modelo_num}_{peca_nome}_{tamanho}"
        det_item = horas_dict[hora_str]["modelos_lancados"][chave_item_hora]

        det_item["produzido"] += reg.quantidade_produzida
        det_item["perda"] += reg.quantidade_perda
        det_item["e_peca"] = e_peca
        det_item["nome_peca"] = peca_nome
        det_item["modelo_num"] = modelo_num
        det_item["tamanho"] = tamanho
        det_item["pares_por_hora"] = prod_h_base

        if det_item["planejado"] == 0:
            det_item["planejado"] = qtd_plan_reg

    # Ordanação do resumo de modelos
    resumo_modelos = sorted(
        modelos_dict.values(),
        key=lambda x: (
            x["e_peca"],
            x["modelo"],
            x["peca"] or "",
            x["numero"],
        ),
    )

    # Construção da lista de baixas por hora
    baixas_por_hora = []
    for hora in sorted(horas_dict.keys(), reverse=True):
        h_data = horas_dict[hora]

        for _, val in h_data["modelos_lancados"].items():
            meta_planejada = val["planejado"]
            prod_h = val["pares_por_hora"]
            produzido = val["produzido"]
            diferenca = produzido - prod_h

            if diferenca < 0:
                status = "Abaixo"
            elif diferenca == 0:
                status = "Na Meta"
            else:
                status = "Acima"

            if val["e_peca"]:
                modelo_peca_label = (
                    f"{val['modelo_num']} (Nº {val['tamanho']}) — {val['nome_peca']}"
                )
            else:
                modelo_peca_label = f"{val['modelo_num']} (Nº {val['tamanho']})"

            baixas_por_hora.append(
                {
                    "hora": hora,
                    "modelo_peca": modelo_peca_label,
                    "meta_planejada": meta_planejada,
                    "prod_h": prod_h,
                    "perda": val["perda"],
                    "produzido": produzido,
                    "diferenca": diferenca,
                    "status": status,
                }
            )

    return {
        "resumo_modelos": resumo_modelos,
        "totais": totais_operador,
        "baixas_por_hora": baixas_por_hora,
        "tem_planejamento": (
            totais_operador["modelo_planejado"] > 0
            or totais_operador["peca_planejada"] > 0
        ),
    }


def processar_relatorio_operadores(registros_qs, page=1, per_page=10):
    """Função principal que coordena o agrupamento, paginação e processamento do relatório de operadores."""
    operador_ids = (
        registros_qs.values_list("item_ficha__ficha__operador__id", flat=True)
        .distinct()
        .order_by("item_ficha__ficha__operador__nome")
    )

    paginator = Paginator(operador_ids, per_page)
    pagina_operadores = paginator.get_page(page)

    registros_pagina = registros_qs.filter(
        item_ficha__ficha__operador__id__in=pagina_operadores.object_list
    )

    operadores_map = _agrupar_registros_por_operador(registros_pagina)
    relatorio_operadores = []

    for op_id, dados in operadores_map.items():
        dados_processados = _processar_dados_operador(dados["registros"])

        relatorio_operadores.append(
            {
                "operador": dados["operador"],
                "resumo_modelos": dados_processados["resumo_modelos"],
                "totais": dados_processados["totais"],
                "baixas_por_hora": dados_processados["baixas_por_hora"],
                "tem_planejamento": dados_processados["tem_planejamento"],
            }
        )

    return relatorio_operadores, pagina_operadores