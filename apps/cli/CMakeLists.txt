add_executable(tae_cli main.cpp)
target_link_libraries(tae_cli PRIVATE tae tae_options)
set_target_properties(tae_cli PROPERTIES OUTPUT_NAME tae)
