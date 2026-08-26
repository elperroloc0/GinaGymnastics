"""this file is created for utility fuctions that will be used within the tracking logic code base"""

"""
цель - вычислять нужно ли давать доступ конкретному родителю чтобы он мог видеть карту

что возвращает функция- true/false

что надо :
    условие - если ребенок находится в поездке (ван вошел в его школу),
    ребенок и время соотвествуют данной школе, тогда даем доступ родителю

    логика кода:
    ван приезжает в геозону школы -- достаем список делей этой школы -- проверяем какие дети едут в этот день -- какие дети едут в этот час (временное окно) -- список детей фильтруем по родителям -- отправляем этим родителям ссылку на карту -- сохраняем детей как active_ride -- по приезду в destination - выключаем active_ride этих детей

    если родитель сам открывает карту:
    есть ли у ребенка active_ride? -- если да пускаем


    кто ребенок?
    кто родитель?
    какое время воз
"""
# active ride function
    #

# ride not active function


# check parent access fuction
    # get parents child
    # if child has active ride
        # return true (access to map)
    # if chils has not active ride or ride >=12h
        # denie access
